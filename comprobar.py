"""Diagnostico del sistema. Ejecutalo ANTES de emitir:

    py -3.11 comprobar.py

Revisa dependencias, modelo, lista de palabras y dispositivos de audio,
y te dice exactamente que falta. Si algo va mal en directo, este es el
primer sitio donde mirar.
"""

from __future__ import annotations

import importlib.metadata as metadatos
import os
import sys

VERDE = "OK   "
ROJO = "FALLO"
AVISO = "AVISO"

problemas: list[str] = []


def linea(estado: str, texto: str, detalle: str = "") -> None:
    print(f"  [{estado}] {texto}")
    if detalle:
        print(f"          {detalle}")


def titulo(texto: str) -> None:
    print(f"\n{texto}\n{'-' * len(texto)}")


titulo("PYTHON")
version = sys.version_info
if version >= (3, 8):
    linea(VERDE, f"Python {version.major}.{version.minor}.{version.micro}")
else:
    linea(ROJO, f"Python {version.major}.{version.minor} es demasiado antiguo")
    problemas.append("Instala Python 3.11")

titulo("DEPENDENCIAS")
for paquete in ("vosk", "sounddevice", "numpy"):
    try:
        linea(VERDE, f"{paquete} {metadatos.version(paquete)}")
    except metadatos.PackageNotFoundError:
        linea(ROJO, f"{paquete} no instalado")
        problemas.append(f"py -3.11 -m pip install {paquete}")

titulo("RECONOCIMIENTO DE VOZ")
try:
    import vosk

    tiene_parciales = hasattr(vosk.KaldiRecognizer, "SetPartialWords")
    if tiene_parciales:
        linea(VERDE, "SetPartialWords disponible", "timestamps en tiempo real")
    else:
        linea(ROJO, "SetPartialWords no disponible")
        problemas.append("Actualiza vosk: py -3.11 -m pip install -U vosk")
    vosk.SetLogLevel(-1)
except ImportError:
    linea(ROJO, "no se puede importar vosk")

titulo("MODELO")
if os.path.isdir("model"):
    faltan = [c for c in ("am", "conf", "graph") if not os.path.isdir(f"model/{c}")]
    if faltan:
        linea(ROJO, "carpeta model incompleta", f"faltan: {', '.join(faltan)}")
        problemas.append("Vuelve a descargar el modelo y descomprimelo en model/")
    else:
        tam = sum(
            os.path.getsize(os.path.join(r, f))
            for r, _, fs in os.walk("model")
            for f in fs
        )
        linea(VERDE, f"modelo espanol cargado ({tam / 1024 / 1024:.0f} MB)")
else:
    linea(ROJO, "no existe la carpeta model/")
    problemas.append("Descarga vosk-model-small-es-0.42 y renombralo a model/")

titulo("LISTA DE PALABRAS")
if os.path.exists("palabras.txt"):
    try:
        from matcher import Detector, leer_lista

        terminos = leer_lista("palabras.txt")
        detector = Detector(terminos)
        sueltas = sum(1 for t in terminos if " " not in t)
        linea(
            VERDE,
            f"{len(terminos)} terminos",
            f"{sueltas} palabras sueltas, {len(terminos) - sueltas} frases",
        )
    except Exception as error:  # noqa: BLE001
        linea(ROJO, "palabras.txt no se puede leer", str(error))
        problemas.append("Revisa palabras.txt")
else:
    linea(ROJO, "no existe palabras.txt")
    problemas.append("Crea palabras.txt")

titulo("DISPOSITIVOS DE AUDIO")
try:
    import sounddevice as sd

    dispositivos = sd.query_devices()
    entradas = [(i, d) for i, d in enumerate(dispositivos) if d["max_input_channels"] > 0]
    salidas = [(i, d) for i, d in enumerate(dispositivos) if d["max_output_channels"] > 0]

    print("\n  ENTRADAS (microfonos):")
    for i, d in entradas:
        print(f"    [{i:2}] {d['name']}")
    print("\n  SALIDAS:")
    for i, d in salidas:
        print(f"    [{i:2}] {d['name']}")

    print()
    cable_salida = [d for _, d in salidas if "cable input" in d["name"].lower()]
    cable_entrada = [d for _, d in entradas if "cable output" in d["name"].lower()]

    if cable_salida:
        linea(VERDE, "VB-CABLE encontrado", f"salida -> {cable_salida[0]['name']}")
    else:
        linea(ROJO, "no se encuentra 'CABLE Input' entre las salidas")
        problemas.append(
            "Instala VB-CABLE desde vb-audio.com/Cable (como administrador) y reinicia"
        )

    if cable_entrada:
        linea(VERDE, "OBS podra capturar de 'CABLE Output'")
    else:
        linea(AVISO, "no se encuentra 'CABLE Output' entre las entradas")

    if not entradas:
        linea(ROJO, "no hay ningun microfono disponible")
        problemas.append("Conecta un microfono y revisa los permisos de Windows")

    # Censurar el audio del PC necesita captura loopback, que no la trae
    # PortAudio. Sin ella el programa funciona, pero solo con el micro.
    import escritorio

    if not escritorio.DISPONIBLE:
        linea(AVISO, "no se puede censurar el audio del PC", escritorio.MOTIVO)
        problemas.append(
            "Para censurar el juego y Discord:  py -3.11 -m pip install PyAudioWPatch"
        )
    else:
        escuchables = escritorio.salidas_capturables()
        if escuchables:
            linea(VERDE, f"se pueden escuchar {len(escuchables)} salidas",
                  f"audio del PC -> {escuchables[-1][1]}")
        else:
            linea(AVISO, "no hay ninguna salida que se pueda escuchar")

    if any("cable-a input" in d["name"].lower() for _, d in salidas):
        linea(VERDE, "segundo cable listo", "el audio del PC ira por CABLE-A")
    else:
        linea(AVISO, "no hay segundo cable (CABLE-A Input)",
              "el audio del PC compartira cable con el microfono")
except Exception as error:  # noqa: BLE001
    linea(ROJO, "no se puede consultar el audio", str(error))

print("\n" + "=" * 60)
if problemas:
    print(f"  {len(problemas)} COSA(S) POR RESOLVER:\n")
    for i, p in enumerate(problemas, 1):
        print(f"    {i}. {p}")
else:
    print("  TODO LISTO. Puedes ejecutar:  py -3.11 main.py")
print("=" * 60 + "\n")

raise SystemExit(1 if problemas else 0)
