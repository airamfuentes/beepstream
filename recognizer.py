"""Reconocimiento de voz en streaming con Vosk, con latencia acotada.

Aqui esta el problema central del proyecto, y no es el que parecia.

Vosk tarda entre 1,1 y 2,4 segundos en comprometer una palabra en sus
resultados parciales. Con un colchon de un segundo, los insultos salian
al directo sin tapar.

La solucion es no esperar a que el decodificador se decida: se le fuerza
a cerrar cada ventana con FinalResult(), que entrega inmediatamente lo
que lleva. El precio es que al cerrar se parte lo que estuviera a
medias, y por eso hay varios reconocedores en paralelo desfasados entre
si: cualquier palabra cae entera en al menos uno.

Los resultados parciales estan APAGADOS. Medido sobre 26 s de voz,
entregaron 0 palabras de 391 —todas salieron de los cierres forzados— y
mantener ese seguimiento encendido costaba un 27% mas de CPU.
"""

from __future__ import annotations

import json
import os

import numpy as np
import vosk

from matcher import PalabraReconocida

FRECUENCIA_VOSK = 16000

# Cada cuanto se fuerza el cierre. La latencia del reconocedor acaba
# siendo practicamente igual a este numero, asi que marca el retardo
# minimo del censor. Medido: 500->510 ms, 600->630 ms, 800->810 ms.
# Por debajo de 500 se empiezan a partir palabras largas.
VENTANA_MS = 800

# Reconocedores solapados. Con 2 se pierden palabras largas, que son
# justo las mas censurables ("gilipollas" dura mas de medio segundo).
CANALES = 3

# Por que 3 x 800 y no los 4 x 600 de antes: con N canales y ventana W
# una palabra cae entera en algun canal mientras dure menos de
# W*(1-1/N), y cada cierre forzado cuesta ~26 ms de CPU. Subir la
# ventana ensancha esa cobertura y ademas abarata. Medido sobre 120
# frases degradadas como llegan por Discord, 3 x 800 detecta mas que
# 4 x 600 gastando un 26% menos. La tabla completa esta en el README.
#
# El precio son 200 ms mas de latencia de deteccion. Con el retardo en
# 1500 ms sobran ~670 ms de margen; por debajo de 1250 hay que volver a
# la ventana de 600.


class Decimador:
    """Convierte 48 kHz a 16 kHz conservando el estado entre bloques.

    Sin el filtro paso bajo previo, las frecuencias por encima de 8 kHz
    se replegarian sobre la banda de voz (aliasing) y empeorarian el
    reconocimiento justo en las consonantes sordas (s, f, ch), que son
    las que distinguen muchas palabras.
    """

    def __init__(self, factor: int = 3, taps: int = 49) -> None:
        self.factor = factor
        self.filtro = self._disenar_filtro(taps, corte=0.45 / factor)
        self.cola = np.zeros(len(self.filtro) - 1, dtype=np.float32)
        self.fase = 0

    @staticmethod
    def _disenar_filtro(taps: int, corte: float) -> np.ndarray:
        """FIR paso bajo por ventana de Hamming. `corte` es fraccion de fs."""
        n = np.arange(taps, dtype=np.float64) - (taps - 1) / 2.0
        respuesta = 2.0 * corte * np.sinc(2.0 * corte * n)
        ventana = np.hamming(taps)
        filtro = respuesta * ventana
        return (filtro / filtro.sum()).astype(np.float32)

    def procesar(self, bloque: np.ndarray) -> np.ndarray:
        entrada = np.concatenate([self.cola, bloque])
        filtrado = np.convolve(entrada, self.filtro, mode="valid")
        self.cola = entrada[-(len(self.filtro) - 1) :]

        indices = np.arange(self.fase, len(filtrado), self.factor)
        # La fase que le toca al siguiente bloque, para que la rejilla de
        # muestreo sea continua aunque los bloques no midan un multiplo
        # exacto del factor de decimacion.
        self.fase = (self.fase - len(filtrado)) % self.factor
        return filtrado[indices]


class Realce:
    """Sube la voz floja al nivel que el reconocedor entiende mejor.

    La voz que llega por el loopback del PC no viene como un microfono:
    alguien hablando por Discord en mitad de una partida puede quedarse
    en -35 dBFS, con el juego por encima. Vosk transcribe bastante peor
    ahi, y lo que no transcribe no se censura.

    Esto SOLO toca la copia que se transcribe, nunca el audio que va al
    directo: subirle el volumen a lo que se emite seria otra cosa muy
    distinta y no es lo que se quiere.

    Dos cuidados:

      · nunca baja, solo sube. Atenuar no ayuda a reconocer.
      · por debajo del suelo no hace nada. Amplificar 24 dB de puro
        ruido de fondo es la forma mas rapida de que el modelo empiece a
        inventarse palabras, y cada palabra inventada es un pitido
        encima de algo que nadie ha dicho.
    """

    def __init__(self, objetivo_dbfs: float = -20.0, maximo_db: float = 24.0,
                 suelo_dbfs: float = -55.0, suavizado: float = 0.15) -> None:
        self.objetivo = 10.0 ** (objetivo_dbfs / 20.0)
        self.maximo = 10.0 ** (maximo_db / 20.0)
        self.suelo = 10.0 ** (suelo_dbfs / 20.0)
        self.suavizado = suavizado
        self.ganancia = 1.0

    def reiniciar(self) -> None:
        self.ganancia = 1.0

    def procesar(self, bloque: np.ndarray) -> np.ndarray:
        nivel = float(np.sqrt(np.mean(bloque**2))) if len(bloque) else 0.0

        if nivel > self.suelo:
            deseada = min(max(self.objetivo / nivel, 1.0), self.maximo)
        else:
            deseada = 1.0

        # Se persigue el valor deseado poco a poco. De golpe, cada
        # explosion del juego pegaria un tiron de volumen a la voz y el
        # reconocedor lo notaria mas que el ruido.
        self.ganancia += (deseada - self.ganancia) * self.suavizado

        if self.ganancia <= 1.001:
            return bloque
        return np.clip(bloque * self.ganancia, -1.0, 1.0).astype(np.float32)


class _Canal:
    """Un reconocedor al que se le fuerza a soltar lo que lleve cada ventana.

    Se usa Reset() en vez de crear un reconocedor nuevo: construirlo
    cuesta unos 100 ms y hacerlo cada 800 ms disparaba la CPU a la mitad
    de un nucleo. Reset() ademas conserva el reloj interno, asi que los
    tiempos que devuelve Vosk siguen siendo absolutos desde el arranque y
    no hay que corregirlos.
    """

    def __init__(self, modelo, ventana_s: float, primer_corte_s: float,
                 alternativas: int = 0) -> None:
        self._rec = vosk.KaldiRecognizer(modelo, FRECUENCIA_VOSK)
        self._rec.SetWords(True)
        # SetPartialWords queda apagado a proposito (ver cabecera).
        if alternativas > 1:
            # Que Vosk no entregue solo su mejor apuesta, sino las N que
            # se planteaba. Para un censor eso es justo lo que hace
            # falta: si alguien vocaliza mal, la palabrota suele estar en
            # la segunda o la tercera hipotesis mientras la primera dice
            # algo inocente. Los tiempos vienen en todas, asi que el
            # pitido se puede colocar igual de bien.
            self._rec.SetMaxAlternatives(alternativas)
        self._ventana = ventana_s
        self.proximo_corte = primer_corte_s

    @staticmethod
    def _palabras(bruto: str) -> list[dict]:
        """Saca las palabras de un resultado, venga en el formato que venga.

        Sin alternativas Vosk devuelve {"result": [...]}. Con ellas,
        {"alternatives": [{"text":..., "result": [...]}, ...]}. Se juntan
        las de todas, quitando las repetidas: la misma palabra en el
        mismo instante no aporta nada dos veces, y duplicarla enganaria
        al detector de frases.
        """
        datos = json.loads(bruto)
        if "result" in datos:
            return datos["result"]

        vistas, palabras = set(), []
        for alternativa in datos.get("alternatives", []):
            for entrada in alternativa.get("result", []):
                clave = (entrada.get("word", ""), round(float(entrada.get("start", 0)), 2))
                if clave in vistas:
                    continue
                vistas.add(clave)
                palabras.append(entrada)
        palabras.sort(key=lambda e: float(e.get("start", 0)))
        return palabras

    def alimentar(self, pcm: bytes, ahora: float) -> list[dict]:
        """Devuelve las palabras crudas vistas en este bloque."""
        if self._rec.AcceptWaveform(pcm):
            # Vosk ha detectado un silencio y ha cerrado por su cuenta.
            self.proximo_corte = ahora + self._ventana
            return self._palabras(self._rec.Result())

        if ahora >= self.proximo_corte:
            # Se acabo la ventana: se le fuerza a soltar lo que tenga sin
            # esperar a que se decida por su cuenta.
            crudas = self._palabras(self._rec.FinalResult())
            self._rec.Reset()
            self.proximo_corte = ahora + self._ventana
            return crudas

        return []

    def cerrar(self) -> list[dict]:
        return self._palabras(self._rec.FinalResult())


# El modelo se carga una vez por proceso y se comparte.
#
# Censurando micro y audio del PC hay dos reconocedores, y cada uno
# cargaba su copia: unos 40 MB de mas y un par de segundos extra al
# arrancar, para tener dos veces exactamente los mismos datos. Vosk
# permite colgar varios KaldiRecognizer de un mismo Model, que es
# justo lo que hace falta.
_MODELOS: dict[str, vosk.Model] = {}


def cargar_modelo(ruta: str) -> vosk.Model:
    modelo = _MODELOS.get(ruta)
    if modelo is None:
        modelo = vosk.Model(ruta)
        _MODELOS[ruta] = modelo
    return modelo


class Reconocedor:
    """Envuelve a Vosk y entrega palabras con tiempos absolutos."""

    def __init__(
        self,
        ruta_modelo: str,
        confianza_minima: float = 0.0,
        ventana_ms: int = VENTANA_MS,
        canales: int = CANALES,
        alternativas: int = 0,
    ) -> None:
        if not os.path.isdir(ruta_modelo):
            raise FileNotFoundError(
                f"No existe la carpeta del modelo: {ruta_modelo}\n"
                "Descarga vosk-model-small-es-0.42 y descomprímelo ahí."
            )

        vosk.SetLogLevel(-1)  # sin ruido de Kaldi en la consola
        self.modelo = cargar_modelo(ruta_modelo)
        self.confianza_minima = confianza_minima
        self.ventana_s = ventana_ms / 1000.0
        self.n_canales = max(2, int(canales))
        self.alternativas = int(alternativas)
        self.decimador = Decimador()
        self._tiempo = 0.0
        self._canales = self._crear_canales()

    def _crear_canales(self) -> list:
        """Canales repartidos uniformemente dentro de la ventana.

        Con N canales hay un cierre cada ventana/N, y una palabra cae
        entera en alguno mientras dure menos de ventana*(1 - 1/N). Subir
        N no baja la latencia (esa la marca la ventana) pero si permite
        acortar la ventana sin perder palabras largas.
        """
        paso = self.ventana_s / self.n_canales
        return [
            _Canal(self.modelo, self.ventana_s, paso * (k + 1), self.alternativas)
            for k in range(self.n_canales)
        ]

    def reiniciar(self) -> None:
        self.decimador = Decimador()
        self._tiempo = 0.0
        self._canales = self._crear_canales()

    def _convertir(self, crudas: list[dict]) -> list[PalabraReconocida]:
        palabras = []
        for entrada in crudas:
            texto = entrada.get("word", "")
            if not texto or texto == "[unk]":
                continue
            confianza = float(entrada.get("conf", 1.0))
            if confianza < self.confianza_minima:
                continue
            palabras.append(
                PalabraReconocida(
                    texto=texto,
                    inicio=float(entrada["start"]),
                    fin=float(entrada["end"]),
                    confianza=confianza,
                )
            )
        return palabras

    def alimentar(self, bloque_48k: np.ndarray) -> tuple[list[PalabraReconocida], bool]:
        """Procesa un bloque de audio y devuelve (palabras, es_final).

        Las palabras vienen de los dos canales, ordenadas por tiempo. Que
        una misma palabra aparezca en ambos no es problema: el motor
        fusiona los tramos que se solapan antes de tapar nada.
        """
        muestras_16k = self.decimador.procesar(bloque_48k)
        if len(muestras_16k) == 0:
            return [], False

        pcm = np.clip(muestras_16k, -1.0, 1.0)
        pcm = (pcm * 32767.0).astype(np.int16).tobytes()
        self._tiempo += len(muestras_16k) / FRECUENCIA_VOSK

        palabras: list[PalabraReconocida] = []
        for canal in self._canales:
            crudas = canal.alimentar(pcm, self._tiempo)
            if crudas:
                palabras.extend(self._convertir(crudas))

        palabras.sort(key=lambda p: p.inicio)
        return palabras, False

    def vaciar(self) -> list[PalabraReconocida]:
        """Fuerza el cierre de todos los canales (al parar el censor)."""
        palabras: list[PalabraReconocida] = []
        for canal in self._canales:
            palabras.extend(self._convertir(canal.cerrar()))
        palabras.sort(key=lambda p: p.inicio)
        return palabras
