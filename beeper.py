"""Generacion y carga del sonido de censura.

El estilo se elige en config.json con `beep_estilo`:

  · tono     - el clasico: senoide de 800 Hz que se repite. Estridente.
  · suave    - senoide grave de 520 Hz sostenida, con cuerpo.
  · shhh     - ruido filtrado, tipo censura de radio. El que menos
               destaca sobre la voz y el que mejor aguanta las frases
               largas, porque no tiene tono que se repita.
  · marimba  - nota de madera que decae y se repite.
  · burbuja  - dos notas que bajan, tipo notificacion.
  · aire     - soplo grave casi inaudible.
  · archivo  - el beep.wav que haya en la carpeta.

Los estilos son de dos familias, y eso cambia como se rellenan los
tramos largos:

  SOSTENIDOS (suave, shhh, aire): un lecho continuo del que se recorta
  lo que haga falta. Entra y sale con rampa **una sola vez por tramo**,
  no en cada repeticion, asi que una frase de dos segundos suena como
  un unico sonido y no como "bip-bip-bip".

  REPETIDOS (tono, marimba, burbuja): un golpe con forma propia que se
  encadena hasta cubrir el tramo. Ahi el ritmo es parte del efecto.

Sobre lo "suave" del sonido, tres cosas influyen y las tres se ajustan
desde config.json:

  · el TONO. 1000 Hz cae justo donde el oido humano es mas sensible y
    resulta estridente. Por debajo de 800 Hz se vuelve mucho mas amable
    sin dejar de oirse con claridad. (Solo afecta al estilo `tono`.)
  · el VOLUMEN. Va como ganancia sobre lo que suene, sea el sonido
    generado o el beep.wav de la carpeta.
  · la RAMPA de entrada y salida. Sin ella el corte seco produce un
    "clic" que en un directo canta mas que el propio pitido. Cuanto mas
    larga, mas suave entra.
"""

from __future__ import annotations

import os
import wave

import numpy as np

# Valores de reserva por si se llama sin parametros. Los de verdad
# viven en config.json.
TONO_HZ = 800.0
VOLUMEN = 0.22  # ~ -13 dBFS: se oye sin taladrar
RAMPA_MS = 20.0


def generar_tono(
    duracion_ms: int,
    frecuencia: int,
    tono_hz: float = TONO_HZ,
    volumen: float = VOLUMEN,
    rampa_ms: float = RAMPA_MS,
) -> np.ndarray:
    """Crea un tono senoidal en float32 mono con rampas anticlic."""
    n = max(1, int(frecuencia * duracion_ms / 1000.0))
    t = np.arange(n, dtype=np.float32) / frecuencia
    onda = np.sin(2.0 * np.pi * tono_hz * t).astype(np.float32) * volumen

    rampa = max(1, int(frecuencia * rampa_ms / 1000.0))
    if n > rampa * 2:
        subida = np.linspace(0.0, 1.0, rampa, dtype=np.float32)
        onda[:rampa] *= subida
        onda[-rampa:] *= subida[::-1]
    else:
        # Pitido mas corto que las dos rampas: se le da forma de campana
        # para que no entre ni salga de golpe.
        ventana = np.hanning(n).astype(np.float32)
        onda *= ventana

    return onda


def _envolvente(n: int, frecuencia: int, subida_ms: float, bajada_ms: float) -> np.ndarray:
    """Rampas de entrada y salida para un golpe suelto."""
    e = np.ones(n, dtype=np.float32)
    a = min(int(frecuencia * subida_ms / 1000.0), n // 2)
    b = min(int(frecuencia * bajada_ms / 1000.0), n // 2)
    if a > 0:
        e[:a] = np.linspace(0.0, 1.0, a, dtype=np.float32)
    if b > 0:
        e[-b:] = np.linspace(1.0, 0.0, b, dtype=np.float32)
    return e


def _segundos(n: int, frecuencia: int) -> np.ndarray:
    return np.arange(n, dtype=np.float32) / frecuencia


def _normalizar(x: np.ndarray) -> np.ndarray:
    pico = float(np.max(np.abs(x))) if len(x) else 0.0
    return x / pico if pico > 0 else x


def _ciclable(x: np.ndarray, frecuencia: int, cruce_ms: float = 40.0) -> np.ndarray:
    """Hace que un lecho de ruido empalme consigo mismo sin chasquido.

    Al repetirse, el final y el principio se encuentran de golpe y eso
    suena como un clic cada vuelta. Se arregla fundiendo la cola sobre
    la cabeza: el punto de union deja de existir.
    """
    cruce = min(int(frecuencia * cruce_ms / 1000.0), len(x) // 4)
    if cruce <= 0:
        return x
    cabeza, cola = x[:-cruce].copy(), x[-cruce:]
    rampa = np.linspace(0.0, 1.0, cruce, dtype=np.float32)
    cabeza[:cruce] = cabeza[:cruce] * rampa + cola * (1.0 - rampa)
    return cabeza


# --- lechos sostenidos: se recorta de ellos lo que dure el tramo ---

def _lecho_suave(n: int, frecuencia: int) -> np.ndarray:
    """Senoide grave con un armonico, para que tenga cuerpo y no pite."""
    t = _segundos(n, frecuencia)
    onda = np.sin(2.0 * np.pi * 520.0 * t) + 0.18 * np.sin(2.0 * np.pi * 1040.0 * t)
    return _normalizar(onda.astype(np.float32))


def _lecho_shhh(n: int, frecuencia: int) -> np.ndarray:
    """Ruido filtrado: la censura de radio de toda la vida.

    Sin tono definido, asi que no hay nada que se repita ni que choque
    con la musica de fondo, y tapa la voz mejor que un pitido al mismo
    volumen. La semilla es fija para que suene igual en cada arranque.
    """
    rng = np.random.default_rng(7)
    x = rng.standard_normal(n + frecuencia // 10).astype(np.float32)
    for _ in range(4):  # paso bajo: quita el siseo mas agudo
        x = np.convolve(x, np.ones(24, dtype=np.float32) / 24, mode="same")
    # y se le resta su propia media larga, que es un paso alto: sin esto
    # queda un retumbe grave que enturbia la mezcla.
    x -= np.convolve(x, np.ones(240, dtype=np.float32) / 240, mode="same")
    return _ciclable(_normalizar(x[:n]), frecuencia)


def _lecho_aire(n: int, frecuencia: int) -> np.ndarray:
    """Soplo grave muy tenue, lo menos intrusivo que se puede poner."""
    rng = np.random.default_rng(3)
    x = rng.standard_normal(n + frecuencia // 10).astype(np.float32)
    for _ in range(9):
        x = np.convolve(x, np.ones(48, dtype=np.float32) / 48, mode="same")
    x = _normalizar(x[:n]) * 0.55
    x = x + 0.45 * np.sin(2.0 * np.pi * 180.0 * _segundos(n, frecuencia)).astype(np.float32)
    return _ciclable(_normalizar(x), frecuencia)


# --- golpes que se encadenan: el ritmo es parte del efecto ---

def _golpe_marimba(frecuencia: int) -> np.ndarray:
    """Nota de madera: armonicos que caen rapido."""
    n = int(frecuencia * 0.260)
    t = _segundos(n, frecuencia)
    nota = (np.sin(2.0 * np.pi * 587.0 * t)
            + 0.50 * np.sin(2.0 * np.pi * 1174.0 * t)
            + 0.25 * np.sin(2.0 * np.pi * 1761.0 * t)).astype(np.float32)
    nota *= np.exp(-t * 11.0).astype(np.float32)
    return _normalizar(nota * _envolvente(n, frecuencia, 3, 10))


def _golpe_burbuja(frecuencia: int) -> np.ndarray:
    """Dos notas que bajan, como un aviso amable."""
    n = int(frecuencia * 0.320)
    t = _segundos(n, frecuencia)
    barrido = 700.0 - 260.0 * np.clip(t / 0.28, 0.0, 1.0)  # 700 -> 440 Hz
    fase = 2.0 * np.pi * np.cumsum(barrido) / frecuencia
    nota = np.sin(fase).astype(np.float32) * np.exp(-t * 4.5).astype(np.float32)
    return _normalizar(nota * _envolvente(n, frecuencia, 8, 20))


# Duracion del lecho de los estilos sostenidos. Dos segundos cubren de
# sobra cualquier frase, y en 520 y 180 Hz caben ciclos exactos, asi que
# tambien empalman sin salto si hiciera falta repetirlos.
LECHO_MS = 2000

SOSTENIDOS = {
    "suave": _lecho_suave,
    "shhh": _lecho_shhh,
    "aire": _lecho_aire,
}

REPETIDOS = {
    "marimba": _golpe_marimba,
    "burbuja": _golpe_burbuja,
}

ESTILOS = ("tono", "suave", "shhh", "marimba", "burbuja", "aire", "archivo")


def generar_estilo(
    estilo: str,
    duracion_ms: int,
    frecuencia: int,
    tono_hz: float = TONO_HZ,
    volumen: float = VOLUMEN,
    rampa_ms: float = RAMPA_MS,
) -> tuple[np.ndarray, bool]:
    """Devuelve (muestras, es_sostenido) del estilo pedido."""
    if estilo in SOSTENIDOS:
        n = max(1, int(frecuencia * LECHO_MS / 1000.0))
        return SOSTENIDOS[estilo](n, frecuencia) * volumen, True
    if estilo in REPETIDOS:
        return REPETIDOS[estilo](frecuencia) * volumen, False
    return generar_tono(duracion_ms, frecuencia, tono_hz, volumen, rampa_ms), False


def guardar_wav(ruta: str, muestras: np.ndarray, frecuencia: int) -> None:
    enteros = np.clip(muestras, -1.0, 1.0)
    enteros = (enteros * 32767.0).astype(np.int16)
    with wave.open(ruta, "wb") as fichero:
        fichero.setnchannels(1)
        fichero.setsampwidth(2)
        fichero.setframerate(frecuencia)
        fichero.writeframes(enteros.tobytes())


def _remuestrear(muestras: np.ndarray, origen: int, destino: int) -> np.ndarray:
    """Ajusta la frecuencia por interpolacion lineal.

    Para un pitido no hace falta nada mas sofisticado: es un tono puro y
    corto, y cualquier artefacto de interpolacion queda por debajo de lo
    audible.
    """
    if origen == destino:
        return muestras
    n_destino = int(round(len(muestras) * destino / origen))
    if n_destino <= 0:
        return muestras
    posiciones = np.linspace(0, len(muestras) - 1, n_destino, dtype=np.float64)
    return np.interp(posiciones, np.arange(len(muestras)), muestras).astype(np.float32)


def cargar_wav(ruta: str, frecuencia_destino: int) -> np.ndarray:
    """Lee un WAV, lo pasa a mono float32 y lo adapta a la frecuencia."""
    with wave.open(ruta, "rb") as fichero:
        canales = fichero.getnchannels()
        ancho = fichero.getsampwidth()
        frecuencia = fichero.getframerate()
        crudo = fichero.readframes(fichero.getnframes())

    tipos = {1: np.uint8, 2: np.int16, 4: np.int32}
    if ancho not in tipos:
        raise ValueError(f"{ruta}: profundidad de {ancho * 8} bits no soportada")

    datos = np.frombuffer(crudo, dtype=tipos[ancho])
    if ancho == 1:  # 8 bits sin signo, centrado en 128
        muestras = (datos.astype(np.float32) - 128.0) / 128.0
    else:
        muestras = datos.astype(np.float32) / float(2 ** (ancho * 8 - 1))

    if canales > 1:  # mezcla a mono
        muestras = muestras.reshape(-1, canales).mean(axis=1)

    return _remuestrear(muestras, frecuencia, frecuencia_destino)


class Beep:
    """El sonido de censura listo para insertarse en el flujo de audio."""

    def __init__(
        self,
        ruta: str,
        duracion_ms: int,
        frecuencia: int,
        volumen: float = VOLUMEN,
        tono_hz: float = TONO_HZ,
        rampa_ms: float = RAMPA_MS,
        estilo: str = "tono",
        bucle: bool = True,
    ) -> None:
        self.frecuencia = frecuencia
        self.estilo = estilo
        self.rampa_ms = rampa_ms
        self.bucle = bucle
        self.sostenido = False
        self.origen = f"generado ({estilo})"

        if estilo == "archivo":
            self.muestras = self._del_archivo(
                ruta, duracion_ms, volumen, tono_hz, rampa_ms)
        else:
            self.muestras, self.sostenido = generar_estilo(
                estilo, duracion_ms, frecuencia, tono_hz, volumen, rampa_ms)

        if len(self.muestras) == 0:
            self.muestras = generar_tono(
                duracion_ms, frecuencia, tono_hz, volumen, rampa_ms)
            self.sostenido = False

    def _del_archivo(self, ruta, duracion_ms, volumen, tono_hz, rampa_ms) -> np.ndarray:
        """Carga beep.wav. Si no hay o no se puede leer, cae al tono."""
        if not os.path.exists(ruta):
            self.origen = "generado (no hay beep.wav)"
            return generar_tono(
                duracion_ms, self.frecuencia, tono_hz, volumen, rampa_ms)
        try:
            muestras = cargar_wav(ruta, self.frecuencia)
        except (ValueError, wave.Error, EOFError):
            # Un beep.wav corrupto no puede tumbar el censor: se cae al
            # tono sintetico y se sigue.
            self.origen = "generado (beep.wav ilegible)"
            return generar_tono(
                duracion_ms, self.frecuencia, tono_hz, volumen, rampa_ms)

        self.origen = f"archivo ({os.path.basename(ruta)})"
        # El volumen se aplica tambien al beep.wav propio, para que el
        # ajuste de la ventana funcione igual con los dos.
        pico = float(np.max(np.abs(muestras))) if len(muestras) else 0.0
        return muestras * (volumen / pico) if pico > 0 else muestras

    def __len__(self) -> int:
        return len(self.muestras)

    @property
    def duracion_ms(self) -> float:
        return 1000.0 * len(self.muestras) / self.frecuencia

    @property
    def pico_db(self) -> float:
        """Nivel de pico en dBFS, para poder enseñarlo en la ventana."""
        pico = float(np.max(np.abs(self.muestras))) if len(self.muestras) else 0.0
        return 20.0 * np.log10(max(pico, 1e-9))

    def _rampas(self, desplazamiento: int, cantidad: int, largo_tramo: int) -> np.ndarray:
        """Ganancia de entrada y salida referida al tramo COMPLETO.

        Es lo que evita el bip-bip: el sonido no entra y sale en cada
        repeticion, sino una sola vez, al principio y al final de la
        palabra censurada, aunque por medio pasen veinte bloques de
        audio distintos.
        """
        subida = max(1.0, self.frecuencia * self.rampa_ms / 1000.0)
        bajada = max(1.0, self.frecuencia * self.rampa_ms * 2.0 / 1000.0)
        # No se puede gastar en rampas mas de la mitad del tramo, o un
        # tramo corto no llegaria nunca a sonar del todo.
        tope = max(1.0, largo_tramo / 2.0)
        subida, bajada = min(subida, tope), min(bajada, tope)

        k = np.arange(cantidad, dtype=np.float32) + desplazamiento
        entrada = np.clip(k / subida, 0.0, 1.0)
        salida = np.clip((largo_tramo - k) / bajada, 0.0, 1.0)
        return np.minimum(entrada, salida).astype(np.float32)

    def tramo(
        self,
        desplazamiento: int,
        cantidad: int,
        bucle: bool | None = None,
        largo_tramo: int | None = None,
    ) -> np.ndarray:
        """Devuelve `cantidad` muestras del sonido desde `desplazamiento`.

        `desplazamiento` se cuenta desde el principio del tramo
        censurado, no desde el principio del bloque de audio, para que
        un tramo que abarque varios bloques suene continuo.

        `largo_tramo` es lo que dura la censura entera. Con los estilos
        sostenidos sirve para colocar las rampas donde toca; sin el, se
        recorta del lecho sin mas.

        Cuando el tramo dura mas que el sonido, `bucle` decide si se
        repite hasta cubrirlo o si el resto se rellena con silencio. En
        ambos casos la voz original no vuelve: lo que se censura, se
        censura completo.
        """
        if cantidad <= 0:
            return np.zeros(0, dtype=np.float32)

        repetir = self.bucle if bucle is None else bucle
        total = len(self.muestras)

        if self.sostenido:
            indices = (np.arange(cantidad) + desplazamiento) % total
            salida = self.muestras[indices].copy()
            if largo_tramo:
                salida *= self._rampas(desplazamiento, cantidad, largo_tramo)
            return salida

        if repetir:
            indices = (np.arange(cantidad) + desplazamiento) % total
            return self.muestras[indices]

        salida = np.zeros(cantidad, dtype=np.float32)
        if desplazamiento < total:
            disponible = min(cantidad, total - desplazamiento)
            salida[:disponible] = self.muestras[
                desplazamiento : desplazamiento + disponible
            ]
        return salida


def desde_config(config) -> Beep:
    """Construye el sonido de censura con los ajustes de config.json."""
    return Beep(
        config.ruta_beep,
        config.beep_ms,
        config.frecuencia,
        volumen=float(config.beep_volumen),
        tono_hz=float(config.beep_tono_hz),
        rampa_ms=float(config.beep_rampa_ms),
        estilo=str(getattr(config, "beep_estilo", "tono")),
        bucle=config.modo_beep == "bucle",
    )
