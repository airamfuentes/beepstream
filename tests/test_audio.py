"""Comprueba que los flujos de audio se abren de verdad.

    py -3.11 tests/test_audio.py

Abre el microfono y la salida con los parametros de config.json, captura
unos segundos y confirma que el reconocedor procesa. NO emite sonido: el
flujo de salida se abre para validar que admite la configuracion, pero
no se arranca.

Es la comprobacion que separa "el programa arranca" de "el audio va".
"""

from __future__ import annotations

import os
import sys

# Se ejecutan desde la raiz del proyecto (py -3.11 tests/test_audio.py),
# asi que hay que meter esa raiz en la ruta de importacion: Python solo
# pone ahi la carpeta del propio fichero.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time

import numpy as np
import sounddevice as sd

import config as cfg
import dispositivos
import rutas
from engine import TAMANO_BLOQUE_MS
from matcher import Detector, leer_lista, leer_seguras
from recognizer import Reconocedor

rutas.preparar()
ajustes = cfg.cargar()
frecuencia = ajustes.frecuencia
bloque = int(frecuencia * TAMANO_BLOQUE_MS / 1000)

fallos = 0


def comprobar(etiqueta, condicion, detalle=""):
    global fallos
    if not condicion:
        fallos += 1
    print(f"  {'OK  ' if condicion else 'FALLO'}  {etiqueta}")
    if detalle:
        print(f"         {detalle}")


def nombre(dispositivo):
    if dispositivo is None:
        return "(predeterminado del sistema)"
    try:
        return dispositivos.describir(dispositivos.resolver(dispositivo, entrada=True))
    except Exception as error:  # noqa: BLE001
        return f"{dispositivo}  <- {error}"

print("\n== CONFIGURACION ==")
print(f"  Entrada:  {nombre(ajustes.dispositivo_entrada)}")
print(f"  Salida:   {ajustes.dispositivo_salida}")
print(f"  {frecuencia} Hz, bloques de {bloque} muestras ({TAMANO_BLOQUE_MS} ms)")

print("\n== FLUJO DE SALIDA (se abre, no se arranca: no sonara nada) ==")
try:
    salida = sd.OutputStream(
        device=dispositivos.resolver(ajustes.dispositivo_salida, entrada=False),
        channels=max(1, min(int(ajustes.canales_salida), 2)),
        samplerate=frecuencia, blocksize=bloque, dtype="float32")
    salida.close()
    comprobar(f"admite {frecuencia} Hz", True)
except Exception as error:  # noqa: BLE001
    comprobar("se puede abrir la salida", False, str(error))
    print("\n  Si pone 'Error querying device', el dispositivo no existe.")
    print("  Instala VB-CABLE o elige otra salida en config.json.\n")

print("\n== CAPTURA REAL (3 segundos) ==")
capturado: list[np.ndarray] = []


def entrante(indata, frames, tiempo, estado):
    capturado.append(indata[:, 0].copy())

try:
    with sd.InputStream(device=dispositivos.resolver(ajustes.dispositivo_entrada, entrada=True), channels=1,
                        samplerate=frecuencia, blocksize=bloque,
                        dtype="float32", callback=entrante):
        print("  Habla ahora (o quedate callado, tambien vale)…")
        time.sleep(3.0)

    total = sum(len(b) for b in capturado)
    esperado = frecuencia * 3
    comprobar("llegan bloques del microfono", len(capturado) > 50,
              f"{len(capturado)} bloques")
    comprobar("la cantidad de audio cuadra", abs(total - esperado) < frecuencia * 0.3,
              f"{total} muestras, esperadas ~{esperado}")

    audio = np.concatenate(capturado) if capturado else np.zeros(1, dtype=np.float32)
    nivel = float(np.sqrt(np.mean(audio ** 2)))
    pico = float(np.max(np.abs(audio)))
    db = 20 * np.log10(max(nivel, 1e-9))
    print(f"         nivel medio {db:.1f} dBFS, pico {pico:.3f}")
    if pico < 0.001:
        print("         AVISO: silencio absoluto. Revisa que el microfono")
        print("                no este silenciado en Windows.")
    elif pico > 0.99:
        print("         AVISO: el microfono satura. Baja su ganancia.")

except Exception as error:  # noqa: BLE001
    comprobar("se puede abrir el microfono", False, str(error))
    audio = np.zeros(1, dtype=np.float32)

print("\n== RECONOCEDOR SOBRE EL AUDIO CAPTURADO ==")
try:
    detector = Detector(leer_lista(ajustes.ruta_palabras), ajustes.modo_deteccion,
                        leer_seguras(ajustes.ruta_seguras))
    reconocedor = Reconocedor(ajustes.ruta_modelo, ajustes.confianza_minima)

    arranque = time.perf_counter()
    palabras: dict[float, object] = {}
    for i in range(0, len(audio), bloque):
        nuevas, _ = reconocedor.alimentar(audio[i : i + bloque])
        for p in nuevas:
            palabras[round(p.inicio, 2)] = p
    for p in reconocedor.vaciar():
        palabras[round(p.inicio, 2)] = p
    tardanza = time.perf_counter() - arranque

    duracion = len(audio) / frecuencia
    factor = tardanza / duracion if duracion else 0
    comprobar("el reconocedor procesa sin errores", True)
    comprobar("va mas rapido que el tiempo real", factor < 0.5,
              f"{factor:.2f}x tiempo real ({tardanza:.2f}s para {duracion:.1f}s)")

    ordenadas = [palabras[k] for k in sorted(palabras)]
    if ordenadas:
        print(f"         oido: {' '.join(p.texto for p in ordenadas)}")
        encontradas = detector.buscar(ordenadas)
        if encontradas:
            for c in encontradas:
                print(f"         CENSURARIA: '{c.dicho}' -> {c.termino}")
    else:
        print("         no se ha reconocido nada (normal si no has hablado)")
except Exception as error:  # noqa: BLE001
    comprobar("el reconocedor funciona", False, str(error))

print("\n" + "=" * 58)
print(f"  {fallos} FALLO(S)" if fallos else "  AUDIO OK")
print("=" * 58 + "\n")
raise SystemExit(1 if fallos else 0)
