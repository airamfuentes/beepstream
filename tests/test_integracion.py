"""Prueba de integracion: audio -> Vosk -> deteccion -> beep en el audio.

Se ejecuta con:  py -3.11 tests/test_integracion.py fichero.wav

Comprueba la cadena completa sobre un WAV, sin microfono ni VB-CABLE.
Es lo que confirma que el pitido cae exactamente encima de la palabra y
no sobre la frase entera.
"""

from __future__ import annotations

import os
import sys

# Se ejecutan desde la raiz del proyecto (py -3.11 tests/test_integracion.py),
# asi que hay que meter esa raiz en la ruta de importacion: Python solo
# pone ahi la carpeta del propio fichero.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import config as cfg
from beeper import cargar_wav, guardar_wav
from engine import procesar_grabacion
from matcher import Detector, leer_lista, leer_seguras

if len(sys.argv) < 2:
    print(__doc__)
    raise SystemExit(2)

ruta = sys.argv[1]
ajustes = cfg.cargar()
detector = Detector(leer_lista(ajustes.ruta_palabras), ajustes.modo_deteccion,
                    leer_seguras(ajustes.ruta_seguras))

print(f"\nLeyendo {ruta}…")
muestras = cargar_wav(ruta, ajustes.frecuencia)
duracion = len(muestras) / ajustes.frecuencia
print(f"  {duracion:.2f} s a {ajustes.frecuencia} Hz")

print("\nProcesando…")
censurado, encontradas = procesar_grabacion(
    muestras, ajustes, detector, ajustes.ruta_modelo)

print(f"\n{len(encontradas)} deteccion(es):")
for c in encontradas:
    print(f"  {c.inicio:6.2f}s - {c.fin:6.2f}s   "
          f"'{c.dicho}' -> {c.termino}   ({c.duracion * 1000:.0f} ms)")

if encontradas:
    tapado = sum(
        min(len(censurado), int(c.fin * ajustes.frecuencia) + ajustes.muestras(ajustes.margen_despues_ms))
        - max(0, int(c.inicio * ajustes.frecuencia) - ajustes.muestras(ajustes.margen_antes_ms))
        for c in encontradas) / ajustes.frecuencia
    print(f"\n  Audio tapado: {tapado:.2f}s de {duracion:.2f}s "
          f"({100 * tapado / duracion:.0f}%)")
    if tapado / duracion > 0.6:
        print("  AVISO: se esta censurando demasiado. Revisa palabras.txt.")

    intacto = np.array_equal(muestras, censurado)
    print(f"  El audio ha cambiado: {'NO (mal)' if intacto else 'si'}")

guardar_wav("salida_censurada.wav", censurado, ajustes.frecuencia)
print("\n  Escrito: salida_censurada.wav\n")
