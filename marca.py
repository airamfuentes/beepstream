"""Geometria de la marca del programa.

La marca es una onda de audio con una barra solida atravesada por
encima: lo que hace el programa, dicho en una figura. Aqui solo se
calculan rectangulos en coordenadas; quien los pinta decide con que.

El mismo calculo sirve para el icono (Pillow, en
herramientas/generar_iconos.py) y para la cabecera de la ventana
(lienzo de Tkinter, en gui.py). Dibujar la cabecera en vez de cargar un
PNG evita tener una imagen por tema y por tamano, y queda nitida en
pantallas con escalado.

Hay tres versiones de la misma marca segun el tamano: a 16 px no caben
nueve barras, asi que por debajo de cierto ancho se dibujan menos en
lugar de dibujarlas todas ilegibles.
"""

from __future__ import annotations

from typing import NamedTuple


class Figura(NamedTuple):
    """Un rectangulo redondeado de la marca.

    `papel` dice con que color se pinta: "onda" y "censura" van en
    tinta; "aire" va en el color del fondo y solo existe para abrir un
    hueco limpio entre la onda y la barra que la tapa.
    """

    x0: float
    y0: float
    x1: float
    y1: float
    radio: float
    papel: str


class Version(NamedTuple):
    alturas: tuple[float, ...]  # alto de cada barra, sobre el alto util
    hueco: float                # separacion entre barras, en anchos de barra
    ancho_barra: float          # ancho de la barra de censura, sobre el total
    alto_barra: float           # y su alto, sobre el alto util
    aire: float                 # margen libre alrededor, sobre el alto util


VERSIONES: dict[str, Version] = {
    # La barra de censura va de borde a borde: corta la onda entera, que
    # es lo que se entiende a la primera. Ninguna barra baja de 0.58,
    # porque por debajo de ahi el hueco que abre la barra se la come
    # entera y en vez de una onda tachada se ven dos muñones.
    "completo": Version(
        alturas=(0.58, 0.88, 1.00, 0.74, 1.00, 0.88, 0.58),
        hueco=0.72, ancho_barra=1.00, alto_barra=0.175, aire=0.075),
    "medio": Version(
        alturas=(0.72, 1.00, 0.80, 1.00, 0.72),
        hueco=0.62, ancho_barra=1.00, alto_barra=0.20, aire=0.075),
    "minimo": Version(
        alturas=(1.00, 0.84, 1.00),
        hueco=0.55, ancho_barra=1.00, alto_barra=0.26, aire=0.07),
    # A 16 px no hay sitio para una onda: quedan tres manchas y un palo.
    # Ahi se deja solo la barra de censura, que es la parte que
    # identifica al programa, en vez de insinuar algo ilegible.
    "sello": Version(
        alturas=(), hueco=0.0, ancho_barra=1.00, alto_barra=0.34, aire=0.0),
}


def version_para(ancho: float) -> str:
    """Que version de la marca entra en un ancho dado, en pixeles."""
    if ancho >= 44:
        return "completo"
    if ancho >= 24:
        return "medio"
    if ancho >= 11:
        return "minimo"
    return "sello"


def figuras(ancho: float, alto: float, version: str | None = None,
            x: float = 0.0, y: float = 0.0) -> list[Figura]:
    """Las figuras de la marca dentro del area dada, en orden de pintado."""
    v = VERSIONES[version or version_para(ancho)]

    barras = len(v.alturas)
    paso = ancho / (barras + v.hueco * (barras - 1)) if barras else 0.0
    salto = paso * (1.0 + v.hueco)
    centro_y = y + alto / 2.0

    piezas = [
        Figura(x + i * salto, centro_y - alto * fraccion / 2.0,
               x + i * salto + paso, centro_y + alto * fraccion / 2.0,
               paso / 2.0, "onda")
        for i, fraccion in enumerate(v.alturas)
    ]

    medio_ancho = ancho * v.ancho_barra / 2.0
    medio_alto = alto * v.alto_barra / 2.0
    centro_x = x + ancho / 2.0
    caja = (centro_x - medio_ancho, centro_y - medio_alto,
            centro_x + medio_ancho, centro_y + medio_alto)

    if v.aire:
        margen = alto * v.aire
        piezas.append(Figura(caja[0] - margen, caja[1] - margen,
                             caja[2] + margen, caja[3] + margen,
                             medio_alto + margen, "aire"))

    piezas.append(Figura(*caja, medio_alto, "censura"))
    return piezas
