"""Carga y guardado de config.json.

Si el fichero no existe se crea con los valores por defecto. Si existe
pero le faltan claves (porque vienes de una version anterior), se
rellenan sin tocar lo que ya habias configurado.
"""

from __future__ import annotations

import json
import os

import rutas

# Version del programa. Es el unico sitio donde esta escrita: el
# instalador la lee de aqui al compilarse.
VERSION = "1.0.0"

RUTA_CONFIG = "config.json"

# Rutas: se guardan relativas y se entregan absolutas, para que el .exe
# las encuentre esten sueltas o empaquetadas dentro.
CLAVES_RUTA = frozenset(
    {"ruta_modelo", "ruta_palabras", "ruta_seguras", "ruta_beep"}
)

POR_DEFECTO: dict = {
    # --- audio ---
    "dispositivo_entrada": None,  # None = microfono por defecto de Windows
    "dispositivo_salida": "CABLE Input",  # a donde va el audio ya censurado
    "frecuencia": 48000,  # Hz. 48k es lo que espera VB-CABLE
    "canales_salida": 2,  # VB-CABLE es estereo; se duplica el mono

    # --- censura ---
    # Colchon para detectar antes de emitir. Es el ajuste critico: por
    # debajo del peor caso del reconocedor las palabras se escapan.
    # Calibralo con:  py -3.11 herramientas/medir_latencia.py grabacion.wav
    "retardo_ms": 1250,
    "beep_ms": 250,  # duracion del sonido generado (solo estilo "tono")
    "beep_volumen": 0.22,  # 0.0 a 1.0 (~ -13 dBFS)
    "beep_tono_hz": 800,  # Hz. Mas bajo = mas suave (solo estilo "tono")
    "beep_rampa_ms": 20,  # entrada y salida progresivas: evita el clic
    "beep_estilo": "shhh",  # ver el catalogo en beeper.py
    "margen_antes_ms": 80,  # se tapa un poco antes del inicio detectado
    "margen_despues_ms": 80,  # y un poco despues del final
    "modo_beep": "bucle",  # "bucle" cubre todo el tramo | "fijo" suena una vez
    "modo_deteccion": "balanceado",  # estricto | balanceado | agresivo
    "censor_activo": True,

    # --- audio del PC (juego, Discord, musica, alertas) ---
    # Se capta por loopback de WASAPI: se escucha una copia de lo que
    # Windows manda a los cascos, sin enrutar nada y sin retardo para ti.
    "censurar_escritorio": False,
    "dispositivo_escritorio": None,  # None = la salida por defecto
    "dispositivo_salida_escritorio": "CABLE-A Input",
    # Ganancia del audio del PC ya censurado. Se aplica DESPUES de
    # reconocer, para no quitarle senal a Vosk.
    "volumen_escritorio": 1.0,

    # Este canal aprieta mas que el del microfono: ahi hablan otros, con
    # el codec de Discord y el juego encima. Un pitido de mas sobre el
    # juego no molesta; una palabrota de menos cuesta el canal.
    "alternativas_escritorio": 3,  # hipotesis que se le piden a Vosk
    "realce_escritorio": True,  # sube la voz floja antes de transcribirla
    # En balanceado a proposito: es el unico de los tres que no esta
    # medido. Si aun asi se escapan palabras, "agresivo" es el siguiente.
    "modo_deteccion_escritorio": "balanceado",

    "modo_rendimiento": False,  # arranca escondido en la bandeja

    # La guia de instalacion se abre sola la primera vez y ya no vuelve
    # a salir. Sigue estando disponible desde el boton de la ventana.
    "asistente_visto": False,

    # --- reconocimiento ---
    "ruta_modelo": "model",
    "ruta_palabras": "palabras.txt",
    "ruta_seguras": "palabras_seguras.txt",
    "ruta_beep": "beep.wav",
    "confianza_minima": 0.0,  # 0 = censura aunque Vosk dude (mas seguro)
    "tema": "oscuro",  # oscuro | claro
}

# No hay ajuste para escucharte a ti mismo a proposito: seria un tercer
# flujo de audio con riesgo de acople, y OBS ya lo hace mejor.

# Valores de los desplegables de la ventana.
RETARDOS = [750, 1000, 1250, 1500, 2000]
# Peor caso medido del reconocedor (830 ms) mas margen. Por debajo de
# aqui la ventana avisa, porque empiezan a escaparse palabras.
RETARDO_MINIMO_SEGURO = 1250
DURACIONES_BEEP = [150, 200, 250, 300, 400, 500]
VOLUMENES_BEEP = [0.08, 0.12, 0.18, 0.22, 0.30, 0.40, 0.55]
TONOS_BEEP = [500, 600, 700, 800, 1000, 1200]
DECIBELIOS_PC = [0, -3, -6, -9, -12, -15, -18, -24]

NOMBRES_ESTILO = {
    "shhh": "shhh (radio)",
    "suave": "tono suave",
    "marimba": "marimba",
    "burbuja": "burbuja",
    "aire": "aire (casi mudo)",
    "tono": "pitido clasico",
    "archivo": "mi beep.wav",
}


class Config:
    """Diccionario de configuracion con acceso por atributo."""

    def __init__(self, datos: dict, ruta: str = RUTA_CONFIG) -> None:
        self._datos = datos
        self._ruta = ruta

    def __getattr__(self, nombre: str):
        try:
            valor = self._datos[nombre]
        except KeyError as error:
            raise AttributeError(nombre) from error
        if nombre in CLAVES_RUTA and isinstance(valor, str):
            return rutas.resolver(valor)
        return valor

    def __getitem__(self, clave: str):
        return self._datos[clave]

    def __setitem__(self, clave: str, valor) -> None:
        self._datos[clave] = valor

    def como_dict(self) -> dict:
        return dict(self._datos)

    def guardar(self) -> None:
        with open(self._ruta, "w", encoding="utf-8") as fichero:
            json.dump(self._datos, fichero, indent=4, ensure_ascii=False)

    # --- conversiones a muestras, que es lo que usa el motor de audio ---

    def muestras(self, milisegundos: float) -> int:
        return int(self._datos["frecuencia"] * milisegundos / 1000.0)

    @property
    def muestras_retardo(self) -> int:
        return self.muestras(self._datos["retardo_ms"])


def cargar(ruta: str = RUTA_CONFIG) -> Config:
    datos = dict(POR_DEFECTO)

    if os.path.exists(ruta):
        with open(ruta, "r", encoding="utf-8") as fichero:
            try:
                guardado = json.load(fichero)
            except json.JSONDecodeError as error:
                raise SystemExit(
                    f"config.json tiene un error de formato (linea {error.lineno}): "
                    f"{error.msg}\nBorralo para regenerarlo con los valores por defecto."
                )
        datos.update({k: v for k, v in guardado.items() if k in POR_DEFECTO})

    config = Config(datos, ruta)
    config.guardar()  # normaliza el fichero y anade claves nuevas
    return config
