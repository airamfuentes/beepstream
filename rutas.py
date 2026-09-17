"""Resolucion de rutas, que cambia entre ejecutar el .py y el .exe.

Con PyInstaller hay dos carpetas distintas en juego:

  · la del ejecutable, donde el usuario ve y edita sus ficheros;
  · la temporal donde PyInstaller extrae lo que va empaquetado dentro
    (accesible como sys._MEIPASS).

palabras.txt, config.json y beep.wav tienen que vivir en la primera para
que se puedan tocar sin recompilar. Van tambien empaquetados para poder
restaurarlos la primera vez que se arranca.
"""

from __future__ import annotations

import os
import shutil
import sys

# Ficheros que el usuario debe poder abrir y editar con el bloc de notas.
EDITABLES = ("palabras.txt", "palabras_seguras.txt", "config.json", "beep.wav")


def empaquetado() -> bool:
    return getattr(sys, "frozen", False)


def directorio_base() -> str:
    """Donde viven los ficheros editables y donde se escribe."""
    if empaquetado():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def directorio_recursos() -> str:
    """Donde estan los ficheros empaquetados (modelo incluido)."""
    return getattr(sys, "_MEIPASS", directorio_base())


def resolver(nombre: str) -> str:
    """Ruta absoluta de un recurso: primero junto al ejecutable, y si no
    esta ahi, dentro del paquete."""
    if os.path.isabs(nombre):
        return nombre

    junto_al_programa = os.path.join(directorio_base(), nombre)
    if os.path.exists(junto_al_programa):
        return junto_al_programa

    dentro_del_paquete = os.path.join(directorio_recursos(), nombre)
    if os.path.exists(dentro_del_paquete):
        return dentro_del_paquete

    return junto_al_programa  # aun no existe: se creara aqui


def preparar() -> None:
    """Deja el programa listo para trabajar con rutas relativas.

    Fija el directorio de trabajo y, la primera vez que se ejecuta el
    .exe, saca del paquete los ficheros editables para que el usuario
    los tenga a mano.
    """
    base = directorio_base()
    try:
        os.chdir(base)
    except OSError:
        return

    if not empaquetado():
        return

    for nombre in EDITABLES:
        destino = os.path.join(base, nombre)
        if os.path.exists(destino):
            continue
        origen = os.path.join(directorio_recursos(), nombre)
        if os.path.exists(origen):
            try:
                shutil.copy2(origen, destino)
            except OSError:
                pass
