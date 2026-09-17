"""BEEP STREAM - censor de audio en tiempo real para directos.

    py -3.11 main.py                  interfaz grafica (lo normal)
    py -3.11 main.py --consola        sin ventana, para depurar
    py -3.11 main.py --listar         lista los dispositivos de audio
    py -3.11 main.py --entrada 6      fuerza un microfono por indice
    py -3.11 main.py --salida 12      fuerza una salida por indice
"""

from __future__ import annotations

import argparse
import gc
import sys
import time

import rutas

# Antes de nada: situarse en la carpeta del programa. Sin esto, arrancar
# con doble clic desde otra ubicacion (o desde el .exe) haria que no se
# encontrasen palabras.txt, config.json ni el modelo.
rutas.preparar()


def listar_dispositivos() -> None:
    import sounddevice as sd

    dispositivos = sd.query_devices()
    print("\nENTRADAS (microfonos)")
    print("-" * 60)
    for i, d in enumerate(dispositivos):
        if d["max_input_channels"] > 0:
            print(f"  [{i:2}] {d['name']}")

    print("\nSALIDAS")
    print("-" * 60)
    for i, d in enumerate(dispositivos):
        if d["max_output_channels"] > 0:
            marca = "  <- esta" if "cable input" in d["name"].lower() else ""
            print(f"  [{i:2}] {d['name']}{marca}")

    # Las salidas que ademas se pueden escuchar, para censurar el audio
    # del PC. Van sin indice a proposito: ahi se trabaja por nombre,
    # porque la numeracion de PyAudio no es la de sounddevice.
    import escritorio

    print("\nSALIDAS QUE SE PUEDEN ESCUCHAR (audio del PC)")
    print("-" * 60)
    if not escritorio.DISPONIBLE:
        print(f"  no disponible: {escritorio.MOTIVO}")
    else:
        for _, nombre in escritorio.salidas_capturables():
            print(f"  - {nombre}")
    print()


def modo_consola(argumentos) -> int:
    import config as cfg
    from engine import MotorCensor
    from matcher import Detector, leer_lista, leer_seguras

    ajustes = cfg.cargar()
    if argumentos.entrada is not None:
        ajustes["dispositivo_entrada"] = argumentos.entrada
    if argumentos.salida is not None:
        ajustes["dispositivo_salida"] = argumentos.salida
    if argumentos.retardo is not None:
        ajustes["retardo_ms"] = argumentos.retardo

    terminos = leer_lista(ajustes.ruta_palabras)
    detector = Detector(terminos, ajustes.modo_deteccion,
                        leer_seguras(ajustes.ruta_seguras))

    def registrar(mensaje: str, nivel: str = "info") -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {mensaje}")

    print("=" * 60)
    print("  BEEP STREAM  ·  modo consola")
    print("=" * 60)
    print(f"  Retardo   {ajustes.retardo_ms} ms")
    print(f"  Beep      {ajustes.beep_ms} ms")
    print(f"  Terminos  {len(terminos)}")
    print("=" * 60)
    print("  Ctrl+C para parar\n")

    motor = MotorCensor(ajustes, detector, registrar)
    try:
        motor.iniciar()
    except Exception as error:  # noqa: BLE001
        print(f"\nNo se puede iniciar: {error}\n")
        print("Ejecuta  py -3.11 comprobar.py  para ver que falta.\n")
        return 1

    # Todo lo que existe en este momento (modulos, clases, funciones,
    # la lista de terminos) va a seguir existiendo hasta que se cierre
    # el programa: no es basura y nunca lo sera. gc.freeze() lo
    # aparta para que el recolector deje de recorrerlo cada vez que le
    # toca una pasada a fondo. Medido con el modelo cargado: esa pasada
    # costaba entre 3,8 y 5,4 ms, y los bloques de audio son de 30 ms.
    # No cambia nada de lo que hace el programa; lo que se reserve a
    # partir de aqui (audio, reconocedores) se sigue recogiendo igual.
    gc.collect()
    gc.freeze()

    try:
        while True:
            time.sleep(5)
            stats = motor.stats
            print(f"[{time.strftime('%H:%M:%S')}] "
                  f"{stats.censuras} censuras · "
                  f"retardo real {motor.retardo_real_ms:.0f} ms · "
                  f"cortes {stats.cortes_entrada}/{stats.cortes_salida}")
    except KeyboardInterrupt:
        print("\nParando…")
    finally:
        motor.parar()
    return 0


def main() -> int:
    analizador = argparse.ArgumentParser(
        prog="BeepStream", description="Censor de audio en tiempo real para directos.")
    analizador.add_argument("--consola", action="store_true",
                            help="ejecuta sin interfaz grafica")
    analizador.add_argument("--listar", action="store_true",
                            help="lista los dispositivos de audio y sale")
    analizador.add_argument("--entrada", type=int, help="indice del microfono")
    analizador.add_argument("--salida", type=int, help="indice de la salida")
    analizador.add_argument("--retardo", type=int, help="retardo en milisegundos")
    argumentos = analizador.parse_args()

    if argumentos.listar:
        listar_dispositivos()
        return 0

    if argumentos.consola:
        return modo_consola(argumentos)

    try:
        from gui import main as abrir_ventana
    except ImportError as error:
        print(f"No se puede abrir la interfaz: {error}")
        print("Prueba con:  py -3.11 main.py --consola")
        return 1

    abrir_ventana()
    return 0


if __name__ == "__main__":
    sys.exit(main())
