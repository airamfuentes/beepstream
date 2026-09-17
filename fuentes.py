"""Carga de las tipografias que acompañan al programa.

La ventana usa Inter, que no viene con Windows. En vez de pedirle al
usuario que la instale, se registra solo para este proceso con
AddFontResourceEx: al cerrar el programa desaparece y no deja nada en el
sistema.

Hay que llamar a `preparar()` ANTES de crear la ventana de Tkinter. Tk
pregunta a Windows por las tipografias disponibles cuando arranca y se
queda con esa lista, asi que una fuente registrada despues no la ve.

Si el registro falla (permisos, fichero que falta, Windows que dice que
no) no pasa nada: se cae a Segoe UI, que esta en todas las instalaciones
desde Vista.
"""

from __future__ import annotations

import os
import sys

import rutas

CARPETA = os.path.join("recursos", "fuentes")

FICHEROS = ("Inter-Regular.ttf", "Inter-Medium.ttf",
            "Inter-SemiBold.ttf", "Inter-Bold.ttf")

# Por orden de preferencia. Segoe UI Variable Text es la de Windows 11;
# Segoe UI es la de Windows 10 y anteriores.
FAMILIAS = ("Inter", "Segoe UI Variable Text", "Segoe UI")
FAMILIAS_MONO = ("JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New")

FR_PRIVATE = 0x10

_cargadas = False


def preparar() -> int:
    """Registra las tipografias del programa. Devuelve cuantas ha metido."""
    global _cargadas
    if _cargadas or sys.platform != "win32":
        return 0
    _cargadas = True

    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return 0

    gdi32 = ctypes.windll.gdi32
    gdi32.AddFontResourceExW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.LPVOID]
    gdi32.AddFontResourceExW.restype = ctypes.c_int

    metidas = 0
    for nombre in FICHEROS:
        ruta = rutas.resolver(os.path.join(CARPETA, nombre))
        if not os.path.exists(ruta):
            continue
        if gdi32.AddFontResourceExW(ruta, FR_PRIVATE, None):
            metidas += 1
    return metidas


def _primera(disponibles: set[str], candidatas) -> str:
    for nombre in candidatas:
        if nombre in disponibles:
            return nombre
    return candidatas[-1]


def elegir(ventana) -> tuple[str, str]:
    """(familia de texto, familia monoespaciada) de las que haya.

    Se pregunta a la ventana ya creada, que es quien sabe de verdad que
    ha encontrado Tk.
    """
    try:
        from tkinter import font as tkfont
        disponibles = set(tkfont.families(ventana))
    except Exception:  # noqa: BLE001
        return FAMILIAS[-1], FAMILIAS_MONO[-1]
    return _primera(disponibles, FAMILIAS), _primera(disponibles, FAMILIAS_MONO)
