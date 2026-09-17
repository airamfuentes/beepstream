"""Censura de lo que suena por los auriculares: juego, voz, musica, alertas.

El microfono se captura con sounddevice, pero lo que Windows *reproduce*
no se puede capturar asi: PortAudio no expone el loopback de WASAPI
(comprobado tambien en sounddevice 0.5.2, que sigue sin la opcion). Por
eso este canal usa PyAudioWPatch, que es PyAudio con el loopback
compilado, y convive sin problemas con sounddevice porque cada uno abre
su propio flujo.

Lo importante del loopback es lo que NO obliga a hacer: no hay que
enrutar el juego a ningun cable ni instalar mezcladores. Se escucha una
copia de lo que ya va a los auriculares: se sigue oyendo todo en tiempo
real y sin un milisegundo de retardo, y el programa se queda con esa copia
para retrasarla, transcribirla y taparle lo que sobre.

A cambio, el loopback entrega la mezcla YA HECHA. Ahi el juego, Discord
y la musica son el mismo audio y no hay forma de separarlos: lo que se
censura, se censura todo junto.

El camino completo:

    juego + Discord + musica  ->  cascos (los oyes al instante)
                              ->  loopback  ->  retardo  ->  censura
                              ->  VB-CABLE  ->  OBS

Normalmente sale por el mismo cable que el microfono, y OBS recoge esa
mezcla como una sola fuente: alli se le asigna una pista de audio propia
y se manda solo a la plataforma que deba llevar censura. Si se prefiere,
se puede elegir un cable distinto para tenerlos separados en el
mezclador; Windows mezcla sin problema los dos flujos en uno u otro
caso.
"""

from __future__ import annotations

import numpy as np
import sounddevice as sd

import dispositivos
from engine import NucleoCensor
from matcher import Detector
from recognizer import Realce

try:
    import pyaudiowpatch as pyaudio

    DISPONIBLE = True
    MOTIVO = ""
except ImportError as error:  # noqa: BLE001
    pyaudio = None
    DISPONIBLE = False
    MOTIVO = f"falta PyAudioWPatch ({error})"


# Orden de canales de WAVE para 5.1 y 7.1:
#   0 frontal izq   1 frontal der   2 centro   3 subgraves
#   4 trasero izq   5 trasero der   6 lateral izq   7 lateral der
#
# El centro se reparte entre los dos lados porque es donde viven las
# voces de la mayoria de los juegos, que es justo lo que hay que
# censurar. Los subgraves se descartan: no llevan voz y solo aportan
# retumbe. Los traseros y laterales entran a media voz.
GANANCIA_CENTRO = 0.707
GANANCIA_TRASEROS = 0.5


def mezclar_estereo(bloque: np.ndarray) -> np.ndarray:
    """Pasa a estereo lo que llegue, sea mono, estereo o 7.1.

    Unos auriculares con sonido envolvente entregan ocho canales aunque
    casi todo venga en los dos primeros. Sumarlos a lo bruto bajaria el
    volumen a la cuarta parte y perderia la voz del centro, asi que se
    hace una mezcla con criterio.
    """
    canales = bloque.shape[1]
    if canales == 1:
        return np.repeat(bloque, 2, axis=1)
    if canales == 2:
        return bloque.copy()

    izq = bloque[:, 0].copy()
    der = bloque[:, 1].copy()
    if canales > 2:  # centro
        izq += GANANCIA_CENTRO * bloque[:, 2]
        der += GANANCIA_CENTRO * bloque[:, 2]
    for i in range(4, canales):  # traseros y laterales; el 3 es el subgraves
        if i % 2 == 0:
            izq += GANANCIA_TRASEROS * bloque[:, i]
        else:
            der += GANANCIA_TRASEROS * bloque[:, i]

    return np.stack([izq, der], axis=1)


def salidas_capturables() -> list[tuple[str, str]]:
    """Salidas de Windows que se pueden escuchar, como (clave, nombre).

    La clave es el nombre del dispositivo, no su indice: los indices de
    PyAudio y los de sounddevice son numeraciones distintas y mezclarlos
    seria pedir a gritos capturar el aparato equivocado.
    """
    if not DISPONIBLE:
        return []

    audio = pyaudio.PyAudio()
    try:
        vistos, salida = set(), []
        for info in audio.get_loopback_device_info_generator():
            nombre = str(info["name"]).replace(" [Loopback]", "").strip()
            if nombre in vistos:
                continue
            vistos.add(nombre)
            salida.append((nombre, nombre))
        return salida
    finally:
        audio.terminate()


class MotorEscritorio(NucleoCensor):
    """Escucha una salida de Windows, la censura y la manda al cable."""

    def __init__(self, config, detector: Detector, al_registrar=None) -> None:
        realce = Realce() if getattr(config, "realce_escritorio", True) else None
        super().__init__(
            config, detector, al_registrar, canales=2, etiqueta="PC · ",
            alternativas=int(getattr(config, "alternativas_escritorio", 0)),
            realce=realce,
        )
        self._audio = None
        self._flujo_entrada = None
        self._canales_entrada = 2
        self.dispositivo_usado = ""
        # Se puede cambiar en marcha desde la ventana. Se aplica al
        # final del todo, cuando ya se ha reconocido y censurado: bajarlo
        # antes le quitaria senal a Vosk y se escaparian palabras.
        self.ganancia = float(getattr(config, "volumen_escritorio", 1.0))

    # ---------------------------------------------------------------
    #  Entrada: copia de lo que Windows manda a los cascos
    # ---------------------------------------------------------------

    def _buscar_loopback(self, audio) -> dict:
        """El dispositivo a escuchar, por nombre o el predeterminado."""
        pedido = self.config.dispositivo_escritorio
        if not pedido:
            return audio.get_default_wasapi_loopback()

        buscado = str(pedido).strip().lower()
        for info in audio.get_loopback_device_info_generator():
            if buscado in str(info["name"]).lower():
                return info

        raise RuntimeError(
            f"No se encuentra la salida '{pedido}' entre las que se pueden\n"
            "escuchar. Puede que la hayas desconectado o que Windows la\n"
            "haya cambiado de nombre: vuelve a elegirla en la ventana."
        )

    def _callback_entrada(self, datos, cuentas, tiempos, estado):
        """Llega desde el hilo de PyAudio. Solo hace cuentas y encola.

        Va entero dentro de un try: si esto lanzase una excepcion,
        PyAudio cerraria el flujo sin decir nada y el canal se quedaria
        mudo para siempre mientras la ventana sigue poniendo ACTIVO. Un
        bloque perdido no se nota; el flujo cerrado, si.
        """
        try:
            bloque = np.frombuffer(datos, dtype=np.float32)
            bloque = bloque.reshape(-1, self._canales_entrada)
            estereo = mezclar_estereo(bloque)
            np.clip(estereo, -1.0, 1.0, out=estereo)

            self.linea.escribir(estereo)

            # Para reconocer da igual la imagen estereo, y en mono Vosk
            # trabaja con la mitad de datos.
            mono = estereo.mean(axis=1).astype(np.float32)
            # np.dot es la suma de cuadrados sin crear el array
            # intermedio, y esto se ejecuta 33 veces por segundo.
            self.nivel = float(np.sqrt(np.dot(mono, mono) / len(mono)))
            pico = max(float(mono.max()), -float(mono.min()))
            if pico > self.nivel_maximo:
                self.nivel_maximo = pico

            self._encolar(mono)
        except Exception:  # noqa: BLE001
            self.stats.cortes_entrada += 1

        return (None, pyaudio.paContinue)

    # ---------------------------------------------------------------
    #  Salida hacia el cable
    # ---------------------------------------------------------------

    def _callback_salida(self, outdata, frames, tiempo, estado) -> None:
        if estado.output_underflow:
            self.stats.cortes_salida += 1

        muestras = self._emitir(frames)
        if muestras is None:
            outdata[:] = 0
            return

        if self.ganancia != 1.0:
            muestras *= self.ganancia

        if outdata.shape[1] == 1:
            outdata[:, 0] = muestras.mean(axis=1)
        else:
            outdata[:, :2] = muestras

    @property
    def entrada_viva(self) -> bool:
        """Si el flujo de captura sigue abierto.

        Hace falta preguntarlo asi porque el loopback de WASAPI no
        entrega NADA mientras no suene nada en el PC: quedarse sin
        muestras es lo normal en una pausa del juego, no una averia.
        """
        try:
            return (self._flujo_entrada is not None
                    and self._flujo_entrada.is_active())
        except Exception:  # noqa: BLE001
            return False

    # ---------------------------------------------------------------
    #  Control
    # ---------------------------------------------------------------

    def iniciar(self) -> None:
        if self._hilo is not None:
            return
        if not DISPONIBLE:
            raise RuntimeError(
                "No se puede escuchar el audio del PC: " + MOTIVO + ".\n\n"
                "Instalalo con:  py -3.11 -m pip install PyAudioWPatch"
            )

        self._audio = pyaudio.PyAudio()
        try:
            info = self._buscar_loopback(self._audio)
            self._canales_entrada = int(info["maxInputChannels"])
            frecuencia = int(info["defaultSampleRate"])
            self.dispositivo_usado = str(info["name"]).replace(" [Loopback]", "")

            if frecuencia != self.frecuencia:
                # Remuestrear dentro del camino de audio traeria mas
                # problemas que soluciones; se pide que coincidan, que
                # ademas es como viene Windows de fabrica.
                raise RuntimeError(
                    f"'{self.dispositivo_usado}' esta a {frecuencia} Hz y el "
                    f"censor trabaja a {self.frecuencia} Hz.\n\n"
                    "Panel de control de Sonido > esa salida > Propiedades >\n"
                    f"Opciones avanzadas > ponla en {self.frecuencia} Hz."
                )

            destino = dispositivos.resolver(
                self.config.dispositivo_salida_escritorio, entrada=False)

            # Escuchar el mismo cable por el que se escribe seria un
            # bucle: lo censurado vuelve a entrar, se retrasa otra vez y
            # el directo se llena de ecos que van a peor.
            nombre_destino = ""
            if destino is not None:
                nombre_destino = str(sd.query_devices(destino)["name"])
            if dispositivos.mismo_aparato(self.dispositivo_usado, nombre_destino):
                raise RuntimeError(
                    f"No se puede escuchar '{self.dispositivo_usado}' y sacar "
                    "el audio por ese mismo cable:\nlo censurado volveria a "
                    "entrar y se realimentaria.\n\n"
                    "En 'Escuchar' elige los auriculares, no un cable."
                )

            self._arrancar_nucleo()

            self._flujo_entrada = self._audio.open(
                format=pyaudio.paFloat32,
                channels=self._canales_entrada,
                rate=frecuencia,
                input=True,
                input_device_index=int(info["index"]),
                frames_per_buffer=self.bloque,
                stream_callback=self._callback_entrada,
            )

            self._salida, usada = dispositivos.abrir(
                lambda idx: sd.OutputStream(
                    device=idx,
                    channels=2,
                    samplerate=self.frecuencia,
                    blocksize=self.bloque,
                    dtype="float32",
                    callback=self._callback_salida,
                ),
                destino,
                entrada=False,
                que_es="el cable del audio del PC",
            )
        except Exception:
            # Si algo falla a mitad hay que soltar lo que ya se abrio, o
            # el dispositivo se queda cogido hasta cerrar el programa.
            self.parar()
            raise

        if usada != destino:
            self._al_registrar(
                f"El cable elegido para el audio del PC no abria; se usa "
                f"{dispositivos.describir(usada)}.", "error")

        self._al_registrar(
            f"Audio del PC en marcha: se escucha '{self.dispositivo_usado}' "
            f"({self._canales_entrada} canales) y sale por "
            f"{dispositivos.describir(usada)}.", "ok")

    def parar(self) -> None:
        self._parar.set()

        if self._flujo_entrada is not None:
            try:
                self._flujo_entrada.stop_stream()
                self._flujo_entrada.close()
            except Exception:  # noqa: BLE001
                pass
            self._flujo_entrada = None

        if self._salida is not None:
            try:
                self._salida.stop()
                self._salida.close()
            except sd.PortAudioError:
                pass
            self._salida = None

        if self._audio is not None:
            try:
                self._audio.terminate()
            except Exception:  # noqa: BLE001
                pass
            self._audio = None

        estaba = self._hilo is not None
        self._parar_nucleo()
        if estaba:
            self._al_registrar("Audio del PC detenido.", "info")
