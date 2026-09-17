"""Prueba de extremo a extremo a traves de VB-CABLE.

    py -3.11 tests/test_cable.py fichero.wav

Comprueba lo unico que ninguna otra prueba puede comprobar: que el audio
YA CENSURADO sale de verdad por CABLE Input y se puede recoger en CABLE
Output, que es exactamente de donde lo lee Streamlabs.

Usa el motor real (su buffer de retardo, su hilo de reconocimiento y su
callback de salida). Lo unico simulado es el microfono: en vez de
capturar, se le van entregando los bloques del WAV al mismo ritmo al que
llegarian en directo.

Al terminar dice si encontro el pitido en el audio recogido del cable.
"""

from __future__ import annotations

import os
import sys

# Se ejecutan desde la raiz del proyecto (py -3.11 tests/test_cable.py),
# asi que hay que meter esa raiz en la ruta de importacion: Python solo
# pone ahi la carpeta del propio fichero.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time

import numpy as np
import sounddevice as sd

import config as cfg
import dispositivos
import rutas
from beeper import cargar_wav, guardar_wav
from engine import TAMANO_BLOQUE_MS, MotorCensor
from matcher import Detector, leer_lista, leer_seguras
from recognizer import Reconocedor

rutas.preparar()

if len(sys.argv) < 2:
    print(__doc__)
    raise SystemExit(2)

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


def energia_del_tono(muestras: np.ndarray, tono_hz: float) -> np.ndarray:
    """Energia del pitido a lo largo del tiempo, ventana a ventana.

    Se compara la energia en la frecuencia del beep contra la energia
    total, para distinguir el pitido de la voz aunque el nivel sea bajo.
    """
    ventana = 2048
    salto = 512
    proporciones = []
    for i in range(0, max(1, len(muestras) - ventana), salto):
        trozo = muestras[i : i + ventana] * np.hanning(ventana)
        espectro = np.abs(np.fft.rfft(trozo))
        frecuencias = np.fft.rfftfreq(ventana, 1 / frecuencia)
        cerca = np.abs(frecuencias - tono_hz) < 40
        total = float(np.sum(espectro)) + 1e-9
        proporciones.append(float(np.sum(espectro[cerca])) / total)
    return np.array(proporciones)


# --------------------------------------------------------------------
#  Preparacion
# --------------------------------------------------------------------
origen = cargar_wav(sys.argv[1], frecuencia)
duracion = len(origen) / frecuencia

detector = Detector(
    leer_lista(ajustes.ruta_palabras), ajustes.modo_deteccion,
    leer_seguras(ajustes.ruta_seguras))

registro: list[str] = []
motor = MotorCensor(ajustes, detector, lambda m, n="info": registro.append(m))

print(f"\n== PRUEBA POR EL CABLE ==")
print(f"  Fichero      : {sys.argv[1]}")
print(f"  Duracion     : {duracion:.1f} s")
print(f"  Salida a     : {ajustes.dispositivo_salida}")
print(f"  Se recoge de : CABLE Output")
print(f"  Retardo      : {ajustes.retardo_ms} ms")
print(f"  Tono del beep: {ajustes.beep_tono_hz} Hz\n")

# --------------------------------------------------------------------
#  Arranque del motor sin microfono: la entrada la damos nosotros
# --------------------------------------------------------------------
motor._reconocedor = Reconocedor(ajustes.ruta_modelo, ajustes.confianza_minima)
motor.linea.vaciar()
motor.registro.vaciar()
motor._lectura = 0
motor._colchon_lleno = False
motor._parar.clear()

hilo_reconocimiento = threading.Thread(
    target=motor._bucle_reconocimiento, daemon=True)
hilo_reconocimiento.start()

salida = sd.OutputStream(
    device=dispositivos.resolver(ajustes.dispositivo_salida, entrada=False),
    channels=max(1, min(int(ajustes.canales_salida), 2)),
    samplerate=frecuencia, blocksize=bloque, dtype="float32",
    callback=motor._callback_salida)

recogido: list[np.ndarray] = []


def entrante(indata, frames, tiempo, estado):
    recogido.append(indata[:, 0].copy())

escucha = sd.InputStream(
    device=dispositivos.resolver("CABLE Output", entrada=True), channels=1,
    samplerate=frecuencia,
    blocksize=bloque, dtype="float32", callback=entrante)

try:
    escucha.start()
    salida.start()

    print("  Enviando audio por el cable…")
    inicio = time.perf_counter()
    for n, i in enumerate(range(0, len(origen), bloque)):
        trozo = origen[i : i + bloque]
        if len(trozo) < bloque:  # ultimo bloque incompleto
            trozo = np.pad(trozo, (0, bloque - len(trozo)))
        motor.linea.escribir(trozo)
        try:
            motor._cola.put_nowait(trozo)
        except Exception:  # noqa: BLE001
            pass
        # Ritmo de directo: un bloque cada 30 ms
        objetivo = inicio + (n + 1) * TAMANO_BLOQUE_MS / 1000.0
        espera = objetivo - time.perf_counter()
        if espera > 0:
            time.sleep(espera)

    # Dejar que salga lo que queda dentro del buffer de retardo
    time.sleep(ajustes.retardo_ms / 1000.0 + 0.5)
finally:
    motor._parar.set()
    salida.stop(); salida.close()
    escucha.stop(); escucha.close()
    hilo_reconocimiento.join(timeout=2.0)

capturado = np.concatenate(recogido) if recogido else np.zeros(1, dtype=np.float32)

# --------------------------------------------------------------------
#  Analisis
# --------------------------------------------------------------------
print("\n== LO QUE HA LLEGADO AL OTRO LADO DEL CABLE ==")
comprobar("llega audio por CABLE Output", len(capturado) > frecuencia,
          f"{len(capturado) / frecuencia:.1f} s recogidos")

pico = float(np.max(np.abs(capturado)))
comprobar("no es silencio", pico > 0.001, f"pico {pico:.3f}")

censuras = [m for m in registro if m.startswith("CENSURANDO")]
tardias = [m for m in registro if m.startswith("TARDE")]

print(f"\n== CENSURAS DETECTADAS ({len(censuras)}) ==")
for m in censuras:
    print(f"    {m}")
if tardias:
    print(f"\n  {len(tardias)} TARDIA(S):")
    for m in tardias:
        print(f"    {m}")

# Un clip sin insultos debe dar cero censuras: eso es exito, no fallo.
# Lo que se comprueba siempre es que nada llegue tarde.
if censuras:
    print("  (el clip tiene insultos: se esperan censuras)")
else:
    print("  (el clip esta limpio: cero censuras es lo correcto)")
comprobar("ninguna deteccion llego tarde", len(tardias) == 0,
          "si hay tardias, sube el retardo")

if len(capturado) > frecuencia:
    proporciones = energia_del_tono(capturado, float(ajustes.beep_tono_hz))
    ventanas_con_beep = int(np.sum(proporciones > 0.5))
    segundos_beep = ventanas_con_beep * 512 / frecuencia
    proporcion_total = segundos_beep / (len(capturado) / frecuencia)

    if censuras:
        comprobar("se oye el pitido en el audio del cable",
                  ventanas_con_beep > 5,
                  f"{segundos_beep:.2f} s de pitido en {len(capturado) / frecuencia:.1f} s")
        # El pitido no puede ocuparlo todo: la voz limpia tiene que pasar.
        comprobar("la voz normal sigue pasando", proporcion_total < 0.5,
                  f"{100 * proporcion_total:.0f}% del audio es pitido")
    else:
        comprobar("no hay ningun pitido de mas", ventanas_con_beep <= 5,
                  f"{segundos_beep:.2f} s de pitido en un clip sin insultos")

guardar_wav("salida_por_cable.wav", capturado, frecuencia)
print(f"\n  Guardado: salida_por_cable.wav  (esto es LO QUE OIRIA TIKTOK)")

print("\n" + "=" * 58)
print(f"  {fallos} FALLO(S)" if fallos else "  EL CABLE FUNCIONA")
print("=" * 58 + "\n")
raise SystemExit(1 if fallos else 0)
