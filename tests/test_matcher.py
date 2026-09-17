"""Pruebas del detector. Se ejecuta con:  py -3.11 tests/test_matcher.py

No necesita microfono ni modelo: valida solo la logica de deteccion,
que es donde estan los errores caros (un falso positivo pita encima de
una palabra inocente, un falso negativo deja pasar un insulto a TikTok).
"""

import os
import sys

# Se ejecutan desde la raiz del proyecto (py -3.11 tests/test_matcher.py),
# asi que hay que meter esa raiz en la ruta de importacion: Python solo
# pone ahi la carpeta del propio fichero.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from matcher import Detector, PalabraReconocida, clave_fonetica

LISTA = [
    "puta", "puto", "mierda", "joder", "coño", "cabron", "gilipollas",
    "maricon", "capullo", "polla", "chocho", "zorra", "hijoputa",
    "hijo de puta", "vete a la mierda", "la madre que te pario",
    "me cago en la puta", "subnormal", "forro", "verga", "picha",
]

detector = Detector(LISTA)


def frase(texto: str):
    """Convierte una frase en palabras con tiempos falsos de 0.5 s."""
    return [
        PalabraReconocida(t, i * 0.5, i * 0.5 + 0.4)
        for i, t in enumerate(texto.split())
    ]


def censurar(texto: str) -> str:
    """Aplica el detector y devuelve la frase con los tramos tapados."""
    palabras = frase(texto)
    tapados = set()
    for c in detector.buscar(palabras):
        for i, p in enumerate(palabras):
            if c.inicio <= p.inicio and p.fin <= c.fin:
                tapados.add(i)
    return " ".join(
        "[BEEP]" if i in tapados else p.texto for i, p in enumerate(palabras)
    )

fallos = 0


def comprobar(etiqueta: str, obtenido, esperado):
    global fallos
    ok = obtenido == esperado
    if not ok:
        fallos += 1
    print(f"  {'OK  ' if ok else 'FALLO'}  {etiqueta}")
    if not ok:
        print(f"         esperado: {esperado!r}")
        print(f"         obtenido: {obtenido!r}")

print("\n== FALSOS POSITIVOS (lo que NUNCA debe pitar) ==")
comprobar("'cono' no es 'coño'", censurar("el cono de trafico"), "el cono de trafico")
comprobar("'coco' no es 'chocho'", censurar("me dio un coco"), "me dio un coco")
comprobar("'pollo' no es 'polla'", censurar("comi pollo asado"), "comi pollo asado")
comprobar("'coger' no es 'joder'", censurar("voy a coger el bus"), "voy a coger el bus")
comprobar("'cuerda' no es 'mierda'", censurar("ata la cuerda"), "ata la cuerda")
comprobar("'disputa' contiene puta", censurar("hubo una disputa"), "hubo una disputa")
comprobar("'reputacion' contiene puta", censurar("mala reputacion"), "mala reputacion")
comprobar("'cabra' no es 'cabron'", censurar("una cabra loca"), "una cabra loca")
comprobar("'putada' no esta en lista", censurar("vaya putada"), "vaya putada")
comprobar("'zorro' no es 'zorra'", censurar("el zorro corre"), "el zorro corre")
comprobar("'capulla' no listada", censurar("es una capulla"), "es una capulla")
comprobar("'normal' no es 'subnormal'", censurar("todo normal"), "todo normal")
# La rr es un fonema distinto de la r: si se colapsan, media docena de
# palabras corrientes empiezan a pitar.
comprobar("'foro' no es 'forro'", censurar("en el foro de ayer"), "en el foro de ayer")
comprobar("'pera' no es 'perra'", censurar("una pera madura"), "una pera madura")
comprobar("'coro' no es 'corro'", censurar("canta en el coro"), "canta en el coro")
comprobar("'vega' no es 'verga'", censurar("la vega del rio"), "la vega del rio")
comprobar("'pica' no es 'picha'", censurar("me pica el brazo"), "me pica el brazo")
comprobar("'sora' no es 'zorra'", censurar("dijo sora"), "dijo sora")

print("\n== ORTOGRAFIA Y TILDES ==")
comprobar("con tilde", censurar("que cabrón"), "que [BEEP]")
comprobar("sin tilde", censurar("que cabron"), "que [BEEP]")
comprobar("plural", censurar("son unos cabrones"), "son unos [BEEP]")
comprobar("coño con ñ", censurar("pero coño tio"), "pero [BEEP] tio")
comprobar("mayusculas", censurar("eres un CAPULLO"), "eres un [BEEP]")

print("\n== VARIANTES FONETICAS (como transcribe Vosk de verdad) ==")
comprobar("gilipoyas -> gilipollas", censurar("es un gilipoyas"), "es un [BEEP]")
comprobar("jilipollas", censurar("es un jilipollas"), "es un [BEEP]")
comprobar("gili pollas partido", censurar("es un gili pollas"), "es un [BEEP] [BEEP]")
comprobar("ijoputa sin h", censurar("menudo ijoputa"), "menudo [BEEP]")
comprobar("hijo puta separado", censurar("menudo hijo puta"), "menudo [BEEP] [BEEP]")
comprobar("marikon con k", censurar("no seas marikon"), "no seas [BEEP]")
comprobar("puto con b/v", censurar("el puto amo"), "el [BEEP] amo")

print("\n== FRASES DE VARIAS PALABRAS ==")
comprobar(
    "frase entera",
    censurar("eres un hijo de puta"),
    "eres un [BEEP] [BEEP] [BEEP]",
)
comprobar(
    "frase al final",
    censurar("anda vete a la mierda"),
    "anda [BEEP] [BEEP] [BEEP] [BEEP]",
)
comprobar(
    "frase larga",
    censurar("la madre que te pario"),
    "[BEEP] [BEEP] [BEEP] [BEEP] [BEEP]",
)

print("\n== POSICION EN LA FRASE ==")
comprobar("al principio", censurar("mierda que susto"), "[BEEP] que susto")
comprobar("en mitad", censurar("ese tio es un gilipollas total"), "ese tio es un [BEEP] total")
comprobar("al final", censurar("vaya mierda"), "vaya [BEEP]")
comprobar("dos seguidos", censurar("puto cabron"), "[BEEP] [BEEP]")
comprobar("dos separados", censurar("puta vida y puto trabajo"), "[BEEP] vida y [BEEP] trabajo")
comprobar("nada que censurar", censurar("hola buenas tardes"), "hola buenas tardes")

print("\n== PRIORIDAD DE LA COINCIDENCIA MAS LARGA ==")
palabras = frase("eres un hijo de puta")
coincidencias = detector.buscar(palabras)
comprobar("una sola coincidencia, no dos", len(coincidencias), 1)
comprobar("gana la frase completa", coincidencias[0].termino, "hijo de puta")
# "hijo" arranca en 1.0 y "puta" acaba en 2.4 -> el tramo dura 1.4 s
comprobar("cubre las 3 palabras", round(coincidencias[0].fin - coincidencias[0].inicio, 2), 1.4)

print("\n== INTERVALOS TEMPORALES ==")
palabras = frase("ese tio es un gilipollas")
c = detector.buscar(palabras)[0]
comprobar("inicio de la palabra 5", c.inicio, 2.0)
comprobar("fin de la palabra 5", round(c.fin, 2), 2.4)

print("\n== CLAVES FONETICAS (inspeccion) ==")
for a, b, iguales in [
    ("coño", "cono", False),
    ("chocho", "coco", False),
    ("gilipollas", "gilipoyas", True),
    ("hijoputa", "ijoputa", True),
    ("cabron", "cabrón", True),
    ("polla", "pollo", False),
    ("joder", "coger", False),
    ("vaca", "baca", True),
    ("forro", "foro", False),
    ("perro", "pero", False),
    ("carro", "caro", False),
    ("zorra", "zorra", True),
]:
    ka, kb = clave_fonetica(a), clave_fonetica(b)
    comprobar(f"{a!r}={ka!r} vs {b!r}={kb!r}", ka == kb, iguales)

print(f"\n{'='*54}")
if fallos:
    print(f"  {fallos} FALLO(S)")
else:
    print("  TODO CORRECTO")
print(f"{'='*54}\n")
raise SystemExit(1 if fallos else 0)
