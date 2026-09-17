"""Sistema visual de la ventana: color, tipografia y espaciado.

La paleta es monocroma a proposito. Un censor tiene un solo aviso que
de verdad importa -- "estas emitiendo sin filtrar" -- y si la ventana ya
gasta verdes, ambares y violetas para decorar, ese aviso se pierde entre
los demas. Aqui todo lo que no es texto ni fondo se dibuja en gris, y el
unico color que existe es el rojo de peligro: cuando aparece algo en
rojo, es que hay que mirar.

El resto de estados se distinguen por luminosidad, que es como funciona
la jerarquia en una interfaz bien hecha: lo activo en blanco, lo
disponible en gris medio, lo apagado en gris oscuro.

Las paletas comparten las mismas claves. La ventana pide colores por su
papel ("fondo", "tinta") y nunca por su valor, asi que cambiar de tema
es cambiar de diccionario y repintar.
"""

from __future__ import annotations

PALETAS: dict[str, dict[str, str]] = {
    "oscuro": {
        "fondo": "#0A0A0B",        # lienzo de la ventana
        "panel": "#101013",        # tarjetas
        "panel_alto": "#1A1A1E",   # desplegables y botones dentro de tarjeta
        "hundido": "#0D0D0F",      # registro y medidores: por debajo del panel
        "borde": "#212126",
        "borde_vivo": "#32323A",   # el mismo borde con el raton encima
        "texto": "#FAFAFA",
        "suave": "#A0A0AA",        # texto secundario
        "tenue": "#6A6A75",        # pistas y unidades
        "apagado": "#33333A",      # lo que existe pero no esta activo
        "tinta": "#FAFAFA",        # fondo de la accion principal
        "sobre_tinta": "#0A0A0B",  # texto encima de la accion principal
        "peligro": "#FF5A5F",
        "sobre_peligro": "#0A0A0B",
    },
    "claro": {
        "fondo": "#F5F5F6",
        "panel": "#FFFFFF",
        "panel_alto": "#F0F0F2",
        "hundido": "#F7F7F8",
        "borde": "#E4E4E8",
        "borde_vivo": "#C9C9D0",
        "texto": "#0E0E11",
        "suave": "#5A5A64",
        "tenue": "#8A8A95",
        "apagado": "#D5D5DA",
        "tinta": "#0E0E11",
        "sobre_tinta": "#FAFAFA",
        "peligro": "#D92D20",
        "sobre_peligro": "#FFFFFF",
    },
}

POR_DEFECTO = "oscuro"

# Familias tipograficas. fuentes.preparar() registra Inter para este
# proceso y aplicar_fuentes() escribe aqui lo que Tk haya encontrado de
# verdad, que puede ser Segoe UI si el registro no ha salido.
TEXTO = "Segoe UI"
MEDIA = "Segoe UI"
SEMI = "Segoe UI Semibold"
MONO = "Consolas"

# Escala tipografica. Tamanos en puntos: Tk los escala con el DPI de la
# pantalla, que es lo que hace falta para que la ventana se vea igual en
# un portatil al 150% que en un monitor al 100%.
ESCALA: dict[str, tuple[str, int, str]] = {
    "titulo": ("SEMI", 16, ""),
    "subtitulo": ("TEXTO", 8, ""),
    "seccion": ("SEMI", 8, ""),      # cabeceras de tarjeta, en mayusculas
    "cuerpo": ("TEXTO", 9, ""),
    "fuerte": ("MEDIA", 9, ""),
    "dato": ("SEMI", 13, ""),        # la ultima palabra censurada
    "estado": ("SEMI", 9, ""),
    "boton": ("MEDIA", 9, ""),
    "boton_alto": ("SEMI", 10, ""),
    "micro": ("TEXTO", 8, ""),
    "mono": ("MONO", 8, ""),
}

# Espaciado en pixeles. Todo lo que separa cosas en la ventana sale de
# aqui, para que los margenes sean multiplos entre si y no numeros
# sueltos puestos a ojo.
ESPACIO = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24, "xxl": 32}


def aplicar_fuentes(texto: str, mono: str) -> None:
    """Fija las familias reales despues de preguntarle a Tk."""
    global TEXTO, MEDIA, SEMI, MONO
    TEXTO = texto
    MONO = mono
    # Inter reparte los pesos en familias propias ("Inter SemiBold"); las
    # de Windows los llevan dentro de la misma. Se prueba el nombre
    # compuesto y, si no existe, se usa la familia base.
    MEDIA = texto
    SEMI = texto
    if texto == "Inter":
        MEDIA, SEMI = "Inter Medium", "Inter SemiBold"
    elif texto == "Segoe UI":
        SEMI = "Segoe UI Semibold"


def fuente(rol: str, tamano: int | None = None) -> tuple:
    """La tupla de fuente de Tk para un papel de la escala."""
    familia, puntos, estilo = ESCALA[rol]
    nombre = {"TEXTO": TEXTO, "MEDIA": MEDIA, "SEMI": SEMI, "MONO": MONO}[familia]
    return (nombre, tamano if tamano is not None else puntos, estilo) if estilo \
        else (nombre, tamano if tamano is not None else puntos)


def paleta(nombre: str) -> dict[str, str]:
    return PALETAS.get(nombre, PALETAS[POR_DEFECTO])


def contrario(nombre: str) -> str:
    return "claro" if nombre == "oscuro" else "oscuro"


def mezclar(color_a: str, color_b: str, proporcion: float) -> str:
    """Interpola dos colores hexadecimales. Para degradados de gris."""
    a = tuple(int(color_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(color_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(
        round(x + (y - x) * proporcion) for x, y in zip(a, b))
