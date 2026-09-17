"""Integracion con Windows: identidad, iconos, DPI y barra de titulo.

Son cuatro cosas que Tkinter no sabe hacer y que hay que pedirle a
Windows directamente. Van juntas aqui para que ni la ventana ni el
asistente tengan que saber de ctypes.

El orden importa: `identidad_app()` y `ajustar_dpi()` tienen que
llamarse ANTES de crear la primera ventana. Windows lee las dos al
crear la ventana y despues ya no vuelve a mirarlas.
"""

from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

import rutas

# Identificador de la aplicacion para Windows. Es una cadena libre,
# pero por convencion va como Empresa.Producto.Componente.Version.
ID_APP = "AiramFuentes.BeepStream.Censor.1"

RUTA_ICONO = os.path.join("recursos", "icono.ico")

# --- constantes de la API de Windows --------------------------------
WM_SETICON = 0x0080
ICON_SMALL, ICON_BIG = 0, 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
SM_CXSMICON, SM_CXICON = 49, 11
# Atributo de DWM para la barra de titulo oscura. Desde Windows 10 20H1
# es el 20; en las compilaciones anteriores era el 19.
DWMWA_MODO_OSCURO = (20, 19)


def _en_windows() -> bool:
    return sys.platform == "win32"


def identidad_app() -> bool:
    """Le dice a Windows que esto es una aplicacion propia.

    Sin esto, ejecutando desde el codigo, la barra de tareas agrupa la
    ventana bajo pythonw.exe y enseña el icono de Python en vez del
    nuestro: Windows identifica las ventanas por el AppUserModelID del
    proceso, y si no se declara ninguno hereda el del ejecutable que
    esta corriendo.

    Hay que llamarlo antes de crear ninguna ventana.
    """
    if not _en_windows():
        return False
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ID_APP)
        return True
    except (AttributeError, OSError):
        return False  # Windows anterior a 7: no existe


def ajustar_dpi() -> bool:
    """Marca el proceso como consciente del escalado de pantalla.

    Sin esto, en un portatil al 125% o 150% Windows dibuja la ventana al
    100% y luego la amplia como si fuera una foto: los textos salen
    borrosos. Con la marca puesta, Tk recibe el DPI real y dibuja
    nitido.
    """
    if not _en_windows():
        return False
    try:
        # 2 = por monitor, que es lo correcto con varias pantallas de
        # escalados distintos. Solo existe desde Windows 8.1.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return True
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            return True
        except (AttributeError, OSError):
            return False


def ruta_icono() -> str | None:
    """Donde esta el .ico de la aplicacion, o None si falta."""
    ruta = rutas.resolver(RUTA_ICONO)
    return ruta if os.path.exists(ruta) else None


def poner_icono(ventana) -> bool:
    """Pone el icono de la aplicacion en una ventana.

    Se hace por dos caminos a proposito. `iconbitmap` es el de Tk y
    sirve para las ventanas hijas, que lo heredan. WM_SETICON es el de
    Windows y es el que de verdad mira la barra de tareas y el Alt+Tab;
    ademas se le dan por separado el tamaño pequeño y el grande, para
    que coja de dentro del .ico la medida exacta en vez de escalar una
    cualquiera.
    """
    ruta = ruta_icono()
    if ruta is None:
        return False

    try:
        ventana.iconbitmap(default=ruta)
    except Exception:  # noqa: BLE001
        pass  # Tk viejo o ruta rara: queda el camino de Windows

    if not _en_windows():
        return True

    try:
        user32 = ctypes.windll.user32
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.SendMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

        ventana.update_idletasks()
        hwnd = user32.GetParent(ventana.winfo_id()) or ventana.winfo_id()

        for cual, metrica in ((ICON_SMALL, SM_CXSMICON), (ICON_BIG, SM_CXICON)):
            lado = user32.GetSystemMetrics(metrica) or (16 if cual == ICON_SMALL else 32)
            icono = user32.LoadImageW(None, ruta, IMAGE_ICON, lado, lado,
                                      LR_LOADFROMFILE)
            if icono:
                user32.SendMessageW(hwnd, WM_SETICON, cual, icono)
        return True
    except Exception:  # noqa: BLE001
        return False


def barra_de_titulo(ventana, oscura: bool) -> None:
    """Pone la barra de titulo de Windows a juego con el tema.

    Tk no la dibuja: la dibuja Windows, y por defecto siempre en claro.
    Queda una franja blanca encima de una ventana negra.

    Hay que llamarlo con la ventana ya dibujada o Windows lo ignora.
    """
    if not _en_windows():
        return
    try:
        ventana.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(ventana.winfo_id())
        valor = ctypes.c_int(1 if oscura else 0)
        for atributo in DWMWA_MODO_OSCURO:
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, atributo, ctypes.byref(valor),
                    ctypes.sizeof(valor)) == 0:
                return
    except Exception:  # noqa: BLE001
        pass  # Windows antiguo: se queda con la barra clara


def preparar() -> None:
    """Todo lo que hay que hacer antes de crear la primera ventana."""
    identidad_app()
    ajustar_dpi()
