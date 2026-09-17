"""Muestra como oye Vosk un WAV, palabra por palabra.

    py -3.11 herramientas/transcribir.py fichero.wav

Es la herramienta para afinar palabras.txt. Si un insulto se te escapa,
graba el modo prueba, pasa el WAV por aqui y mira que escribio Vosk
realmente: si dijiste "gilipollas" y transcribio "chiripollas", anade
esa forma a la lista y dejara de escaparse.

Las palabras que activarian el censor salen marcadas.
"""

from __future__ import annotations

import os
import sys

# Se ejecutan desde la raiz del proyecto (py -3.11 herramientas/transcribir.py),
# asi que hay que meter esa raiz en la ruta de importacion: Python solo
# pone ahi la carpeta del propio fichero.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as cfg
from beeper import cargar_wav
from matcher import Detector, leer_lista, leer_seguras
from recognizer import Reconocedor

if len(sys.argv) < 2:
    print(__doc__)
    raise SystemExit(2)

ajustes = cfg.cargar()
detector = Detector(leer_lista(ajustes.ruta_palabras), ajustes.modo_deteccion,
                    leer_seguras(ajustes.ruta_seguras))
muestras = cargar_wav(sys.argv[1], ajustes.frecuencia)
bloque = int(ajustes.frecuencia * 0.03)

reconocedor = Reconocedor(ajustes.ruta_modelo, ajustes.confianza_minima)
# Indexado por inicio: Vosk repite la misma palabra en los sucesivos
# resultados parciales ajustando el final, y nos interesa quedarnos con
# la ultima version, que es la definitiva.
palabras: dict[float, object] = {}

for i in range(0, len(muestras), bloque):
    nuevas, _ = reconocedor.alimentar(muestras[i : i + bloque])
    for p in nuevas:
        palabras[round(p.inicio, 2)] = p
for p in reconocedor.vaciar():
    palabras[round(p.inicio, 2)] = p

ordenadas = [palabras[k] for k in sorted(palabras)]
censuradas = set()
for c in detector.buscar(ordenadas):
    for p in ordenadas:
        if c.inicio <= p.inicio and p.fin <= c.fin:
            censuradas.add((p.inicio, p.fin))

print(f"\nTRANSCRIPCION  ({len(ordenadas)} palabras)")
print("-" * 58)
for p in ordenadas:
    marca = "  <-- CENSURADO" if (p.inicio, p.fin) in censuradas else ""
    print(f"  {p.inicio:6.2f}s  {p.texto:<20} conf {p.confianza:.2f}{marca}")

print("-" * 58)
print("  " + " ".join(
    "[BEEP]" if (p.inicio, p.fin) in censuradas else p.texto for p in ordenadas))
print()
