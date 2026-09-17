"""Auditoria de la lista real de palabras. Se ejecuta con:

    py -3.11 tests/test_falsos_positivos.py

Hace dos cosas sobre palabras.txt tal y como esta, en los tres modos:

  COBERTURA       que los insultos que dices de verdad se pillen.
  FALSOS POSITIVOS que el habla normal pase intacta.

Lo segundo importa tanto como lo primero: un censor que pita cada vez
que dices "cono" o "cargando" es inusable, y solo se descubre en
directo si no se comprueba aqui.
"""

from __future__ import annotations

import os
import sys

# Se ejecutan desde la raiz del proyecto (py -3.11 tests/test_falsos_positivos.py),
# asi que hay que meter esa raiz en la ruta de importacion: Python solo
# pone ahi la carpeta del propio fichero.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as cfg
from matcher import Detector, PalabraReconocida, leer_lista, leer_seguras

# --------------------------------------------------------------------
#  Habla corriente que NUNCA debe activar el censor.
#  Frases completas, porque el detector trabaja sobre ventanas.
# --------------------------------------------------------------------
HABLA_NORMAL = [
    # objetos y animales que suenan a insulto
    "el cono de trafico esta en la carretera",
    "me comi un coco y una pera",
    "el pollo asado con patatas",
    "saca al perro a pasear que la perra duerme",
    "la concha de la playa es bonita",
    "compre huevos leche y pan",
    "quita el polvo de la mesa",
    "el conejo y la almeja del mercado",
    "corta la paja del pajar",
    "el nabo y el rabo de la verdura",
    "una rata salio corriendo",
    # verbos frecuentes
    "esta cargando la partida",
    "voy a cargarme este boss",
    "se esta guardando la configuracion",
    "he guardado la partida",
    "voy a coger el autobus",
    "no quiero que se pierda la conexion",
    "estoy ganando la partida",
    "ata bien la cuerda",
    "el coro canta en el foro",
    # sustantivos varios
    "compre merluza en la pescaderia",
    "el zorro corre por el campo",
    "la cabra sube al monte",
    "hubo una disputa por la reputacion",
    "la vega del rio esta verde",
    "pon la olla en el fuego",
    "el caro y el barato",
    "me pica el brazo",
    "el pato y la pata del banco",
    # expresiones que llevan dentro una palabra de la lista negra
    "se quedo tan pancho despues de todo",
    "el tren va retrasado otra vez",
    "el vuelo va retrasado una hora",
    "vamos retrasados con el calendario",
    # palabras corrientes que ahora estan en la lista como insulto
    "me llego el paquete esta manana",
    "coge la paleta de colores",
    "hay moras en el bosque",
    "la mora esta madura",
    "conoci a un polaco muy majo",
    "llevo botas camperas",
    "ese arma esta muy cheta",
    "me conto una trola enorme",
    "la paleta de padel se rompio",
    "compre un paquete de folios",
    # frases largas de stream
    "buenas noches a todos bienvenidos al directo",
    "vamos a jugar una partida rankeada",
    "gracias por la suscripcion de verdad",
    "dadle like al video y suscribios al canal",
    "ahora mismo estoy configurando el audio",
    "esta partida esta siendo muy complicada",
    "no me lo puedo creer que remontada",
    "voy a bajar un poco el volumen de la musica",
    "el equipo contrario juega muy bien",
    "manana hay directo a la misma hora",
    "vamos a leer los comentarios del chat",
    "que tal estais gente como va todo",
    "se me esta calentando el ordenador",
    "hoy toca stream largo asi que poneos comodos",
    "voy a probar una cosa nueva en el juego",
    "esta zona del mapa es una trampa",
    "necesito curarme antes de seguir",
    "el jefe final tiene mucha vida",
    "menuda suerte he tenido ahi",
    "eso ha estado cerca de verdad",
]

# --------------------------------------------------------------------
#  Insultos que SI deben pillarse, en las formas en que se dicen.
# --------------------------------------------------------------------
DEBE_PILLARSE = [
    "cabron", "cabrones", "cabronazo", "cabrona",
    "gilipollas", "gilipolla", "gilipoyas", "gilipollez",
    "puta", "putas", "puto", "putos", "putada",
    "mierda", "mierdas", "mierdoso",
    "joder", "jodido", "jodete",
    "coño", "coñazo",
    "capullo", "capullos",
    "maricon", "mariconazo", "marica",
    "polla", "pollas", "soplapollas",
    "hostia", "ostia", "hostias",
    "cojones", "cojonudo",
    "subnormal", "subnormales",
    "imbecil", "idiota", "estupido", "cretino",
    "zorra", "guarra", "guarro",
    "hijoputa", "ijoputa", "hijaputa",
    "pendejo", "boludo", "pelotudo", "forro",
    "chocho", "picha", "verga", "culero",
    "mamon", "pringado", "tarado", "anormal",
    "cagada", "cagon", "malparido",
]

# --------------------------------------------------------------------
#  Colisiones conocidas y ACEPTADAS a proposito.
#
#  La palabra esta en palabras.txt porque como insulto es corriente, y
#  su uso inocente es raro en un directo. Se declaran aqui para que el
#  test siga en verde y cualquier colision NUEVA destaque sola.
#
#  Si alguna te molesta: escribela en palabras_seguras.txt.
# --------------------------------------------------------------------
ACEPTADAS = {
    # "eres un capullo" es insulto de uso diario;
    # "el capullo de la rosa" no sale en un directo de juegos.
    "capullo",
}

FRASES_A_PILLAR = [
    "eres un hijo de puta",
    "vete a la mierda ya",
    "la madre que te pario",
    "me cago en la puta",
    "me cago en dios",
    "me cago en la hostia",
    "que te den por culo",
    "no me jodas tio",
    "hasta los cojones estoy",
    "tu puta madre",
    "pedazo de mierda",
    "que cojones haces",
    "chupame la polla",
    "vete a tomar por culo",
]


def como_palabras(texto: str):
    return [
        PalabraReconocida(t, i * 0.5, i * 0.5 + 0.4)
        for i, t in enumerate(texto.split())
    ]


def censurado(detector: Detector, texto: str) -> list[str]:
    """Devuelve las palabras que el detector taparia."""
    palabras = como_palabras(texto)
    tapadas = []
    for c in detector.buscar(palabras):
        for p in palabras:
            if c.inicio <= p.inicio and p.fin <= c.fin:
                tapadas.append(p.texto)
    return tapadas

ajustes = cfg.cargar()
terminos = leer_lista(ajustes.ruta_palabras)
seguras = leer_seguras(ajustes.ruta_seguras)

print(f"\nLista real: {len(terminos)} terminos, {len(seguras)} en lista blanca")

total_fallos = 0

for modo in ("estricto", "balanceado", "agresivo"):
    detector = Detector(terminos, modo, seguras)
    falsos: list[tuple[str, list[str]]] = []
    escapados: list[str] = []

    for frase in HABLA_NORMAL:
        tapadas = [t for t in censurado(detector, frase) if t not in ACEPTADAS]
        if tapadas:
            falsos.append((frase, tapadas))

    for palabra in DEBE_PILLARSE:
        if not censurado(detector, palabra):
            escapados.append(palabra)
    for frase in FRASES_A_PILLAR:
        if not censurado(detector, frase):
            escapados.append(frase)

    objetivo = len(DEBE_PILLARSE) + len(FRASES_A_PILLAR)
    pillados = objetivo - len(escapados)
    print(f"\n{'=' * 60}")
    print(f"  MODO {modo.upper()}")
    print(f"{'=' * 60}")
    print(f"  Cobertura:        {pillados}/{objetivo} "
          f"({100 * pillados / objetivo:.0f}%)")
    print(f"  Falsos positivos: {len(falsos)}/{len(HABLA_NORMAL)} frases")

    if escapados:
        print(f"\n  SE ESCAPAN ({len(escapados)}):")
        for e in escapados:
            print(f"    · {e}")

    if falsos:
        print(f"\n  PITA DE MAS ({len(falsos)}):")
        for frase, tapadas in falsos:
            print(f"    · \"{frase}\"")
            print(f"        tapa: {', '.join(tapadas)}")

    # En estricto se admite menos cobertura: es su razon de ser.
    # Los falsos positivos no se admiten en ningun modo.
    total_fallos += len(falsos)
    if modo != "estricto":
        total_fallos += len(escapados)

print(f"\n{'=' * 60}")
if total_fallos:
    print(f"  {total_fallos} PROBLEMA(S) - revisa arriba")
else:
    print("  LISTA LIMPIA: pilla lo que debe y no pita de mas")
print(f"{'=' * 60}\n")

sys.exit(1 if total_fallos else 0)
