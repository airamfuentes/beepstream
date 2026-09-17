"""Genera las capturas de pantalla del README.

    py -3.11 herramientas/generar_capturas.py

Los nombres de los dispositivos de audio se sustituyen por unos
genericos: las capturas se publican en el repositorio y no tienen por
que llevar el hardware de quien las hizo. Los ajustes tambien se fijan a
los de por defecto, para que la imagen corresponda a lo que ve alguien
que acaba de instalar el programa y no a la configuracion de nadie.

Necesita Pillow, que solo hace falta para esto.
"""

from __future__ import annotations

import os
import sys
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
os.chdir(RAIZ)

try:
    from PIL import ImageGrab
except ImportError:
    sys.exit("Falta Pillow:  py -3.11 -m pip install Pillow")

import rutas

rutas.preparar()

import dispositivos as disp  # noqa: E402
import escritorio  # noqa: E402
import fuentes  # noqa: E402
import gui  # noqa: E402
import sistema  # noqa: E402

DOCS = os.path.join(RAIZ, "docs")

# Lo que se enseña en lugar de los dispositivos reales.
ENTRADAS = [
    (1, "Microfono (USB Audio Device)  [Windows WASAPI]"),
    (2, "Microfono de los auriculares  [Windows WASAPI]"),
]
SALIDAS = [
    (11, "CABLE Input (VB-Audio Virtual Cable)  [Windows WASAPI]"),
    (12, "Altavoces (Realtek Audio)  [Windows WASAPI]"),
    (13, "CABLE-A Input (VB-Audio Cable A)  [Windows WASAPI]"),
]

# Las salidas que se pueden escuchar por loopback salen de otra libreria
# (PyAudioWPatch) y hay que falsearlas aparte.
CAPTURABLES = [
    ("Auriculares", "Auriculares (Realtek Audio)"),
    ("Altavoces", "Altavoces (Realtek Audio)"),
]

# Ajustes de la captura: los de fabrica, mas el canal del PC encendido
# para que se vea la tarjeta entera en vez de a medias.
AJUSTES = {
    "retardo_ms": 1500,
    "beep_ms": 250,
    "beep_estilo": "shhh",
    "beep_volumen": 0.22,
    "censurar_escritorio": True,
    "volumen_escritorio": 0.178,  # -15 dB
    "asistente_visto": True,
    "tema": "oscuro",
    "dispositivo_entrada": 1,
    "dispositivo_salida": 11,
    "dispositivo_escritorio": "Auriculares",
    "dispositivo_salida_escritorio": 13,
}


def falsear_dispositivos() -> None:
    disp.listar = lambda entrada: (ENTRADAS if entrada else SALIDAS)
    escritorio.salidas_capturables = lambda: CAPTURABLES


def recortar(ventana, destino: str) -> None:
    ventana.attributes("-topmost", True)
    ventana.deiconify()
    ventana.lift()
    ventana.update_idletasks()
    ventana.update()
    time.sleep(0.8)
    ventana.update()
    x, y = ventana.winfo_rootx(), ventana.winfo_rooty()
    caja = (x, y, x + ventana.winfo_width(), y + ventana.winfo_height())
    ImageGrab.grab(bbox=caja).save(destino)
    print(os.path.relpath(destino, RAIZ))


def main() -> None:
    os.makedirs(DOCS, exist_ok=True)
    falsear_dispositivos()
    fuentes.preparar()
    sistema.preparar()

    app = gui.Aplicacion()
    for clave, valor in AJUSTES.items():
        app.config_app[clave] = valor
    app.config_app.guardar()
    app.destroy()

    # Se rehace con los ajustes ya escritos, que es como los lee la
    # ventana al construirse.
    app = gui.Aplicacion()

    import asistente
    guia = asistente.Asistente(app)
    guia.withdraw()  # primero la ventana principal, sin nada delante

    def disparar() -> None:
        recortar(app, os.path.join(DOCS, "ventana.png"))
        app._alternar_tema()
        recortar(app, os.path.join(DOCS, "ventana-claro.png"))
        app._alternar_tema()
        app.attributes("-topmost", False)

        for paso, nombre in ((0, "asistente"), (1, "guia-retardo"),
                             (2, "guia-cable"), (5, "guia-video")):
            guia.paso = paso
            guia._mostrar()
            recortar(guia, os.path.join(DOCS, f"{nombre}.png"))
        guia.withdraw()

        import palabras
        editor = palabras.VentanaPalabras(app)
        recortar(editor, os.path.join(DOCS, "palabras.png"))
        editor.destroy()

        app.quit()

    app.after(1200, disparar)
    app.mainloop()


if __name__ == "__main__":
    main()
