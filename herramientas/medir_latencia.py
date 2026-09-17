"""Mide cuanto tarda el reconocedor en confirmar cada palabra.

    py -3.11 herramientas/medir_latencia.py fichero.wav

Es el dato que decide el retardo. Por cada palabra compara:

    · el momento en que se PRONUNCIA   (timestamp que da Vosk)
    · el momento en que se RECONOCE    (cuanto audio se habia metido ya)

La diferencia es el margen que hay que darle al buffer. Si una palabra
tarda 1,4 s en confirmarse y el retardo esta en 1,0 s, esa palabra sale
al directo sin censurar.
"""

from __future__ import annotations

import os
import sys

# Se ejecutan desde la raiz del proyecto (py -3.11 herramientas/medir_latencia.py),
# asi que hay que meter esa raiz en la ruta de importacion: Python solo
# pone ahi la carpeta del propio fichero.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

import config as cfg
import rutas
from beeper import cargar_wav
from engine import TAMANO_BLOQUE_MS
from matcher import Detector, leer_lista, leer_seguras
from recognizer import Reconocedor

rutas.preparar()

if len(sys.argv) < 2:
    print(__doc__)
    raise SystemExit(2)

ajustes = cfg.cargar()
frecuencia = ajustes.frecuencia
bloque = int(frecuencia * TAMANO_BLOQUE_MS / 1000)

detector = Detector(
    leer_lista(ajustes.ruta_palabras), ajustes.modo_deteccion,
    leer_seguras(ajustes.ruta_seguras))
reconocedor = Reconocedor(ajustes.ruta_modelo, ajustes.confianza_minima)

muestras = cargar_wav(sys.argv[1], frecuencia)

# Primera vez que se ve cada palabra: {clave -> (dicha_en, reconocida_en)}
primera_vez: dict[tuple[float, str], float] = {}
censurables: dict[tuple[float, str], float] = {}

alimentado = 0.0
for i in range(0, len(muestras), bloque):
    trozo = muestras[i : i + bloque]
    palabras, _ = reconocedor.alimentar(trozo)
    alimentado = (i + len(trozo)) / frecuencia

    for p in palabras:
        clave = (round(p.inicio, 2), p.texto)
        if clave not in primera_vez:
            primera_vez[clave] = alimentado

    for c in detector.buscar(palabras):
        clave = (round(c.inicio, 2), c.termino)
        if clave not in censurables:
            censurables[clave] = alimentado

print(f"\n== LATENCIA DE RECONOCIMIENTO ==")
print(f"  {sys.argv[1]}")
print(f"  {len(muestras) / frecuencia:.1f} s de audio\n")

if not primera_vez:
    print("  No se ha reconocido nada.\n")
    raise SystemExit(1)

print(f"  {'palabra':<18} {'dicha en':>9} {'vista en':>9} {'retraso':>9}")
print("  " + "-" * 50)
retrasos = []
for (inicio, texto), visto in sorted(primera_vez.items()):
    retraso = visto - inicio
    retrasos.append(retraso)
    print(f"  {texto:<18} {inicio:8.2f}s {visto:8.2f}s {retraso * 1000:7.0f} ms")

retrasos = np.array(retrasos)
print("\n  " + "-" * 50)
print(f"  Retraso medio  : {retrasos.mean() * 1000:6.0f} ms")
print(f"  Mediana        : {np.median(retrasos) * 1000:6.0f} ms")
print(f"  Percentil 95   : {np.percentile(retrasos, 95) * 1000:6.0f} ms")
print(f"  PEOR CASO      : {retrasos.max() * 1000:6.0f} ms")

if censurables:
    print(f"\n== SOLO LAS PALABRAS QUE SE CENSURAN ==")
    print(f"  {'termino':<18} {'dicha en':>9} {'vista en':>9} {'retraso':>9}")
    print("  " + "-" * 50)
    retrasos_malos = []
    for (inicio, termino), visto in sorted(censurables.items()):
        retraso = visto - inicio
        retrasos_malos.append(retraso)
        print(f"  {termino:<18} {inicio:8.2f}s {visto:8.2f}s {retraso * 1000:7.0f} ms")
    peor = max(retrasos_malos)
    print("\n  " + "-" * 50)
    print(f"  PEOR CASO      : {peor * 1000:6.0f} ms")

    # +500 ms y no +250: en frio no se cuenta la cola de proceso ni
    # el extra que necesitan las frases de varias palabras.
    recomendado = int(np.ceil((peor + 0.5) * 1000 / 250) * 250)
    print(f"\n  Retardo actual : {ajustes.retardo_ms} ms")
    print(f"  RECOMENDADO    : {recomendado} ms  (peor caso + 500 ms de margen)")
    if ajustes.retardo_ms < peor * 1000:
        print(f"\n  AVISO: con {ajustes.retardo_ms} ms se te escaparian palabras.")
print()
