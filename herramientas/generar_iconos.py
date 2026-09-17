"""Genera los iconos y las imagenes de documentacion del proyecto.

    py -3.11 herramientas/generar_iconos.py

La forma de la marca vive en marca.py y la comparten este script y la
cabecera de la ventana, asi que las dos cambian a la vez. Pillow solo
hace falta aqui: el programa no lo usa en ningun momento.
"""

from __future__ import annotations

import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Falta Pillow:  py -3.11 -m pip install Pillow")

import marca

RECURSOS = os.path.join(RAIZ, "recursos")
DOCS = os.path.join(RAIZ, "docs")
FUENTES = os.path.join(RECURSOS, "fuentes")

NEGRO = (11, 11, 12, 255)
BLANCO = (250, 250, 250, 255)
GRIS = (124, 124, 134, 255)

# Pillow no suaviza los bordes de las figuras que dibuja, pero si al
# reducir una imagen: se dibuja a 8x y se escala al final.
ESCALA = 8

RADIO_INSIGNIA = 0.2237  # cuadrado redondeado al estilo de los iconos de OS


def area_marca(lado: int) -> tuple[float, float]:
    """Que parte de la insignia ocupa la marca, en ancho y alto.

    Crece segun se encoge el icono: el margen que hace respirar a un
    icono de 256 px se come la figura entera en uno de 16, donde lo que
    hace falta es que la marca ocupe todo lo que pueda.
    """
    if lado <= 24:
        return 0.80, 0.62
    if lado <= 48:
        return 0.74, 0.58
    return 0.66, 0.52


def pintar(lienzo: ImageDraw.ImageDraw, piezas, tinta, fondo,
           censura_hueca: bool = False, grosor: int = 1) -> None:
    for pieza in piezas:
        caja = (pieza.x0, pieza.y0, pieza.x1, pieza.y1)
        if pieza.papel == "aire":
            lienzo.rounded_rectangle(caja, radius=pieza.radio, fill=fondo)
        elif pieza.papel == "censura" and censura_hueca:
            lienzo.rounded_rectangle(caja, radius=pieza.radio,
                                     outline=tinta, width=grosor)
        else:
            lienzo.rounded_rectangle(caja, radius=pieza.radio, fill=tinta)


def insignia(lado: int, fondo=NEGRO, tinta=BLANCO, censura_hueca: bool = False,
             tachada: bool = False) -> Image.Image:
    """La marca dentro de un cuadrado redondeado: el icono de la app."""
    grande = lado * ESCALA
    imagen = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    lienzo = ImageDraw.Draw(imagen)
    lienzo.rounded_rectangle((0, 0, grande - 1, grande - 1),
                             radius=grande * RADIO_INSIGNIA, fill=fondo)

    fraccion_ancho, fraccion_alto = area_marca(lado)
    ancho, alto = grande * fraccion_ancho, grande * fraccion_alto
    # La version se elige con el tamano final, no con el ampliado.
    piezas = marca.figuras(ancho, alto, marca.version_para(lado * fraccion_ancho),
                           (grande - ancho) / 2.0, (grande - alto) / 2.0)
    pintar(lienzo, piezas, tinta, fondo, censura_hueca,
           grosor=max(1, int(grande * 0.016)))

    if tachada:
        margen = grande * 0.20
        for color, ancho_linea in ((fondo, 0.135), (tinta, 0.062)):
            lienzo.line((margen, grande - margen, grande - margen, margen),
                        fill=color, width=int(grande * ancho_linea))

    return imagen.resize((lado, lado), Image.LANCZOS)


def marca_suelta(ancho: int, alto: int, tinta, fondo) -> Image.Image:
    """La marca sin insignia, para cabeceras."""
    imagen = Image.new("RGBA", (ancho * ESCALA, alto * ESCALA), (0, 0, 0, 0))
    piezas = marca.figuras(ancho * ESCALA, alto * ESCALA,
                           marca.version_para(ancho))
    pintar(ImageDraw.Draw(imagen), piezas, tinta, fondo)
    return imagen.resize((ancho, alto), Image.LANCZOS)


def fuente(nombre: str, tamano: int):
    ruta = os.path.join(FUENTES, nombre)
    return (ImageFont.truetype(ruta, tamano) if os.path.exists(ruta)
            else ImageFont.load_default())


def ancho_texto(lienzo, texto: str, tipo, tracking: float) -> float:
    return (sum(lienzo.textlength(letra, font=tipo) for letra in texto)
            + tracking * max(len(texto) - 1, 0))


def centrar(lienzo, ancho_total: int, texto: str, tipo, arriba: float, color,
            tracking: float = 0.0) -> None:
    """Escribe centrado, letra a letra para poder separarlas.

    Pillow no tiene ajuste de tracking y un titulo corto en mayusculas
    sin el se ve apretado.
    """
    x = (ancho_total - ancho_texto(lienzo, texto, tipo, tracking)) / 2.0
    for letra in texto:
        lienzo.text((x, arriba), letra, font=tipo, fill=color)
        x += lienzo.textlength(letra, font=tipo) + tracking


def banner(ancho: int = 1280, alto: int = 420) -> Image.Image:
    """Cabecera del README."""
    imagen = Image.new("RGBA", (ancho, alto), NEGRO)
    lienzo = ImageDraw.Draw(imagen)

    ancho_marca, alto_marca = int(ancho * 0.215), int(alto * 0.30)
    imagen.alpha_composite(marca_suelta(ancho_marca, alto_marca, BLANCO, NEGRO),
                           ((ancho - ancho_marca) // 2, int(alto * 0.165)))

    titulo = fuente("Inter-Bold.ttf", int(alto * 0.135))
    centrar(lienzo, ancho, "BEEP STREAM", titulo, alto * 0.565, BLANCO,
            tracking=alto * 0.020)

    pie = fuente("Inter-Regular.ttf", int(alto * 0.050))
    centrar(lienzo, ancho, "Censor de audio en tiempo real para directos", pie,
            alto * 0.765, GRIS, tracking=alto * 0.003)
    return imagen

TAMANOS_ICO = (16, 20, 24, 32, 48, 64, 128, 256)

# Los cuatro estados del icono de la bandeja del sistema.
ESTADOS = {
    "activo": {},
    "sin_censura": {"censura_hueca": True},
    "silenciado": {"tachada": True},
    "parado": {"tinta": GRIS},
}


def guardar_ico(ruta: str, **opciones) -> None:
    capas = [insignia(lado, **opciones) for lado in TAMANOS_ICO]
    capas[0].save(ruta, format="ICO", append_images=capas[1:],
                  sizes=[(c.width, c.height) for c in capas])


# --------------------------------------------------------------------
#  Imagenes del instalador
# --------------------------------------------------------------------

INSTALADOR = os.path.join(RAIZ, "instalador")

# Inno Setup admite varias resoluciones de la misma imagen y elige segun
# el escalado de la pantalla. Se nombran con el porcentaje detras.
ESCALAS_INNO = (1.0, 1.25, 1.5, 2.0)


def lateral(ancho: int = 164, alto: int = 314) -> Image.Image:
    """La banda vertical de la izquierda del instalador."""
    imagen = Image.new("RGB", (ancho, alto), NEGRO[:3])
    ancho_marca = int(ancho * 0.56)
    alto_marca = int(ancho_marca * 0.42)
    figura = marca_suelta(ancho_marca, alto_marca, BLANCO, NEGRO)
    imagen.paste(figura, ((ancho - ancho_marca) // 2, int(alto * 0.38)), figura)

    lienzo = ImageDraw.Draw(imagen)
    tipo = fuente("Inter-SemiBold.ttf", max(9, int(ancho * 0.080)))
    centrar(lienzo, ancho, "BEEP STREAM", tipo, alto * 0.52, BLANCO,
            tracking=ancho * 0.012)
    return imagen


def esquina(lado: int = 55) -> Image.Image:
    """El icono pequeño de la esquina superior del instalador."""
    imagen = Image.new("RGB", (lado, int(lado * 1.05)), NEGRO[:3])
    insignia_ = insignia(int(lado * 0.78))
    borde = (lado - insignia_.width) // 2
    imagen.paste(insignia_, (borde, borde), insignia_)
    return imagen


def guardar_instalador() -> None:
    os.makedirs(INSTALADOR, exist_ok=True)
    for escala in ESCALAS_INNO:
        sufijo = "" if escala == 1.0 else f"-{int(escala * 100)}"
        lateral(int(164 * escala), int(314 * escala)).save(
            os.path.join(INSTALADOR, f"lateral{sufijo}.bmp"))
        esquina(int(55 * escala)).save(
            os.path.join(INSTALADOR, f"esquina{sufijo}.bmp"))
    print("instalador/lateral*.bmp  ·  instalador/esquina*.bmp")


def main() -> None:
    os.makedirs(RECURSOS, exist_ok=True)
    os.makedirs(DOCS, exist_ok=True)

    guardar_ico(os.path.join(RECURSOS, "icono.ico"))
    print("recursos/icono.ico")
    for estado, opciones in ESTADOS.items():
        guardar_ico(os.path.join(RECURSOS, f"bandeja_{estado}.ico"), **opciones)
        print(f"recursos/bandeja_{estado}.ico")

    insignia(512).save(os.path.join(DOCS, "logo.png"))
    print("docs/logo.png")
    banner().convert("RGB").save(os.path.join(DOCS, "banner.png"), optimize=True)
    print("docs/banner.png")

    guardar_instalador()


if __name__ == "__main__":
    main()
