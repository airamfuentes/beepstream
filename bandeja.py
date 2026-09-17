"""Icono en la bandeja del sistema, sin dependencias externas.

Tkinter no sabe poner iconos en la bandeja, y las librerias que lo hacen
(pystray) arrastran Pillow, que engorda el .exe varios megas para una
funcion pequena. Aqui se habla directamente con la API de Windows a
traves de ctypes.

Windows solo entrega los avisos del icono a una ventana, asi que se crea
una ventana oculta con su propio bucle de mensajes en un hilo aparte. Lo
que el usuario pulsa en el menu no se ejecuta ahi: se deja en una cola
que la ventana de Tkinter vacia en su propio hilo, porque tocar Tkinter
desde otro hilo lo rompe.
"""

from __future__ import annotations

import ctypes
import itertools
import os
import queue
import threading
from ctypes import wintypes

import rutas

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

# Sin argtypes explicitos ctypes asume enteros de 32 bits, y en Windows
# de 64 los handles (hInstance, hwnd, hMenu) y el lParam no caben: la
# llamada muere con OverflowError dentro del hilo, sin rastro. Hay que
# declarar TODA funcion a la que se le pase un handle.
user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
user32.LoadIconW.restype = wintypes.HICON
user32.LoadImageW.argtypes = [
    wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
    ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = wintypes.HANDLE
user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.DestroyMenu.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL
shell32.Shell_NotifyIconW.restype = wintypes.BOOL

WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP_BANDEJA = 0x0400 + 20  # mensaje propio para los avisos del icono
WM_APP_CERRAR = 0x0400 + 21   # 'destruyete', porque DestroyWindow solo
                              # vale desde el hilo dueno de la ventana

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04

SM_CXSMICON = 49  # ancho que Windows quiere para los iconos pequeños

TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
MF_STRING, MF_SEPARATOR, MF_CHECKED = 0x0000, 0x0800, 0x0008

# El icono de la bandeja lleva la marca del programa, con una variante
# por estado: relleno cuando censura, hueco cuando el censor esta
# apagado, tachado cuando el microfono esta silenciado y gris cuando no
# hay nada en marcha. Los genera herramientas/generar_iconos.py.
ICONOS = {
    "activo": "bandeja_activo.ico",
    "sin_censura": "bandeja_sin_censura.ico",
    "silenciado": "bandeja_silenciado.ico",
    "parado": "bandeja_parado.ico",
}

# Si los ficheros no estan (ejecutando desde el codigo sin haberlos
# generado), se cae a los que ya trae Windows. Distinguen peor el
# estado, pero el programa no se queda sin icono.
IDI_APPLICATION = 32512
IDI_WARNING = 32515
IDI_ERROR = 32513
IDI_SHIELD = 32518

ICONOS_SISTEMA = {
    "activo": IDI_SHIELD,
    "sin_censura": IDI_WARNING,
    "silenciado": IDI_ERROR,
    "parado": IDI_APPLICATION,
}

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040
LR_SHARED = 0x8000

def _recurso(numero: int):
    """MAKEINTRESOURCE: los iconos de sistema se piden por numero, pero
    la API espera un puntero, no una cadena."""
    return ctypes.cast(ctypes.c_void_p(numero), wintypes.LPCWSTR)


# Cada bandeja registra su propia clase de ventana. Si compartieran
# nombre, la segunda vez que se pasa a segundo plano Windows
# reutilizaria la clase vieja, que apunta a un WNDPROC ya liberado, y
# el programa se cae al primer mensaje.
_CONTADOR = itertools.count(1)


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
    wintypes.WPARAM, wintypes.LPARAM
)


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class Bandeja:
    """Icono de bandeja con menu. Todo lo pesado ocurre en su propio hilo.

    `opciones` es una lista de (texto, clave). Al pulsar una, la clave se
    encola; la ventana principal la recoge con `pendientes()` y decide
    que hacer. Una clave None dibuja un separador.
    """

    def __init__(self, titulo: str, opciones: list, al_doble_clic: str) -> None:
        self.titulo = titulo
        self.opciones = opciones
        self.al_doble_clic = al_doble_clic
        self._cola: queue.Queue = queue.Queue()
        self._hwnd = None
        self._hilo = None
        self._listo = threading.Event()
        self._estado = "parado"
        self._texto = titulo
        self._iconos: dict = {}
        self.error = ""  # motivo del ultimo fallo, para poder ensenarlo
        self._nombre_clase = f"BeepStreamBandeja{next(_CONTADOR)}"
        # Referencias que deben sobrevivir mientras Windows las use: si
        # el recolector se lleva el WNDPROC, el proceso se cae.
        self._wndproc = None
        self._clase = None

    # ---------------------------------------------------------------

    def _icono(self, estado: str):
        """Handle del icono del estado, cacheado.

        En segundo plano esto se pedia una vez por segundo durante
        horas, y los iconos son siempre los mismos cuatro: se cargan a
        la primera y se reutilizan.

        Se pide el tamaño que diga Windows (SM_CXSMICON) en vez de uno
        fijo: en una pantalla al 150% el icono de 16 px se ve borroso, y
        el .ico lleva dentro todas las medidas para que no haga falta
        escalar ninguna.
        """
        handle = self._iconos.get(estado)
        if handle is not None:
            return handle

        ruta = rutas.resolver(os.path.join("recursos", ICONOS.get(estado, "")))
        if os.path.exists(ruta):
            lado = user32.GetSystemMetrics(SM_CXSMICON) or 16
            handle = user32.LoadImageW(None, ruta, IMAGE_ICON, lado, lado,
                                       LR_LOADFROMFILE)
        if not handle:
            handle = user32.LoadIconW(
                None, _recurso(ICONOS_SISTEMA.get(estado, IDI_APPLICATION)))

        self._iconos[estado] = handle
        return handle

    def _datos(self, estado: str, texto: str) -> NOTIFYICONDATA:
        datos = NOTIFYICONDATA()
        datos.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        datos.hWnd = self._hwnd
        datos.uID = 1
        datos.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        datos.uCallbackMessage = WM_APP_BANDEJA
        datos.hIcon = self._icono(estado)
        datos.szTip = texto[:127]
        return datos

    def _menu(self) -> None:
        menu = user32.CreatePopupMenu()
        for indice, (texto, clave) in enumerate(self.opciones, start=1):
            if clave is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            else:
                user32.AppendMenuW(menu, MF_STRING, indice, texto)

        punto = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(punto))
        # Sin esto el menu se queda pegado si pulsas fuera de el.
        user32.SetForegroundWindow(self._hwnd)
        elegido = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, punto.x, punto.y,
            0, self._hwnd, None)
        user32.PostMessageW(self._hwnd, 0, 0, 0)
        user32.DestroyMenu(menu)

        if 1 <= elegido <= len(self.opciones):
            clave = self.opciones[elegido - 1][1]
            if clave:
                self._cola.put(clave)

    def _procesar(self, hwnd, mensaje, wparam, lparam):
        if mensaje == WM_APP_BANDEJA:
            evento = lparam & 0xFFFF
            if evento in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                self._cola.put(self.al_doble_clic)
            elif evento == WM_RBUTTONUP:
                self._menu()
            return 0
        if mensaje == WM_APP_CERRAR:
            user32.DestroyWindow(hwnd)
            return 0
        if mensaje == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, mensaje, wparam, lparam)

    def _preparar(self) -> None:
        """Registra la clase, crea la ventana oculta y pone el icono.

        Levanta OSError con el codigo de Windows si algo falla, para que
        `mostrar` pueda decir por que en vez de un 'no se pudo' a secas.
        """
        # El callback se crea una sola vez por bandeja y se guarda: si el
        # recolector se lo lleva mientras Windows lo tiene apuntado, el
        # proceso muere sin aviso.
        if self._wndproc is None:
            self._wndproc = WNDPROC(self._procesar)
        clase = WNDCLASS()
        clase.lpfnWndProc = self._wndproc
        clase.lpszClassName = self._nombre_clase
        clase.hInstance = kernel32.GetModuleHandleW(None)
        self._clase = clase
        if not user32.RegisterClassW(ctypes.byref(clase)):
            raise ctypes.WinError()

        self._hwnd = user32.CreateWindowExW(
            0, clase.lpszClassName, self.titulo, 0, 0, 0, 0, 0,
            None, None, clase.hInstance, None)
        if not self._hwnd:
            raise ctypes.WinError()

        if not shell32.Shell_NotifyIconW(
                NIM_ADD, ctypes.byref(self._datos(self._estado, self._texto))):
            raise ctypes.WinError()

    def _bucle(self) -> None:
        try:
            self._preparar()
        except Exception as fallo:  # noqa: BLE001
            self.error = str(fallo)
            # Recoger lo que si llego a crearse, para que un segundo
            # intento parta de cero en vez de chocar con las sobras.
            if self._hwnd:
                user32.DestroyWindow(self._hwnd)
            user32.UnregisterClassW(
                self._nombre_clase, kernel32.GetModuleHandleW(None))
            self._hwnd = None
            return
        finally:
            # Pase lo que pase, `mostrar` deja de esperar: si esto no se
            # avisa, la ventana se queda tres segundos colgada para nada.
            self._listo.set()

        mensaje = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(mensaje), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(mensaje))
            user32.DispatchMessageW(ctypes.byref(mensaje))

    # ---------------------------------------------------------------

    def mostrar(self) -> bool:
        """Crea el icono. Devuelve False si Windows no deja."""
        if self._hilo is not None:
            return True
        self.error = ""
        try:
            self._hilo = threading.Thread(target=self._bucle, daemon=True)
            self._hilo.start()
            if not self._listo.wait(timeout=3.0):
                self.error = "el icono no respondio en 3 segundos"
        except Exception as fallo:  # noqa: BLE001
            self.error = str(fallo)
        if self._hwnd is None:
            self._hilo = None
            return False
        return True

    def actualizar(self, estado: str, texto: str) -> None:
        """Cambia el icono y el texto que sale al pasar el raton.

        Si no ha cambiado nada no se toca a Windows. En segundo plano
        la ventana llama a esto cada segundo, y casi siempre para decir
        exactamente lo mismo que la vez anterior.
        """
        if self._hwnd is None:
            return
        if estado == self._estado and texto == self._texto:
            return
        self._estado, self._texto = estado, texto
        try:
            shell32.Shell_NotifyIconW(
                NIM_MODIFY, ctypes.byref(self._datos(estado, texto)))
        except Exception:  # noqa: BLE001
            pass

    def pendientes(self) -> list:
        """Lo que el usuario ha pulsado desde la ultima vez."""
        acciones = []
        while True:
            try:
                acciones.append(self._cola.get_nowait())
            except queue.Empty:
                return acciones

    def quitar(self) -> None:
        if self._hwnd is None:
            return
        try:
            shell32.Shell_NotifyIconW(
                NIM_DELETE, ctypes.byref(self._datos(self._estado, self._texto)))
            user32.PostMessageW(self._hwnd, WM_APP_CERRAR, 0, 0)
        except Exception:  # noqa: BLE001
            pass
        hilo, self._hilo = self._hilo, None
        self._hwnd = None
        self._listo.clear()
        # Hay que esperar a que la ventana muera de verdad antes de soltar
        # la clase; destruirla es inmediato, el limite es solo por si acaso.
        if hilo is not None:
            hilo.join(timeout=2.0)
        try:
            user32.UnregisterClassW(
                self._nombre_clase, kernel32.GetModuleHandleW(None))
        except Exception:  # noqa: BLE001
            pass
