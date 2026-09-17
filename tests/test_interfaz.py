"""Pruebas de la interfaz. Se ejecuta con:  py -3.11 tests/test_interfaz.py

Aqui se comprueban dos clases de fallo que no da la cara hasta que
alguien abre la ventana, porque en Python no son errores de sintaxis:

  · Un color o un tamano de letra pedido por un nombre que no existe.
    La ventana pide "seccion" o "panel_alto" con una cadena, asi que
    una errata no revienta al importar el modulo sino al pintar, y solo
    en la pantalla concreta donde este ese widget.

  · Que una paleta tenga claves que la otra no. Se veria unicamente al
    cambiar de tema, y solo en las partes afectadas.

Ademas se construyen de verdad la ventana principal, la guia entera
paso a paso y el editor de listas, en los dos temas. Es lento comparado
con el resto de pruebas, pero es lo unico que garantiza que la ventana
abre.

Necesita escritorio: no se puede ejecutar en un servidor sin pantalla.
"""

import os
import sys

# Se ejecutan desde la raiz del proyecto (py -3.11 tests/test_interfaz.py),
# asi que hay que meter esa raiz en la ruta de importacion: Python solo
# pone ahi la carpeta del propio fichero.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ast
import tempfile

import rutas

rutas.preparar()

import listas  # noqa: E402
import marca  # noqa: E402
import tema as tm  # noqa: E402

fallos: list[str] = []


def comprobar(condicion: bool, texto: str) -> None:
    estado = "OK   " if condicion else "FALLO"
    print(f"  [{estado}] {texto}")
    if not condicion:
        fallos.append(texto)


# --------------------------------------------------------------------
#  Paleta y escala tipografica
# --------------------------------------------------------------------

def probar_tema() -> None:
    print("\nTEMA\n" + "-" * 60)

    claves = [set(p) for p in tm.PALETAS.values()]
    comprobar(all(c == claves[0] for c in claves),
              "las paletas clara y oscura tienen las mismas claves")

    colores = [v for p in tm.PALETAS.values() for v in p.values()]
    comprobar(all(c.startswith("#") and len(c) == 7 for c in colores),
              "todos los colores son hexadecimales de seis digitos")

    comprobar(all(isinstance(tm.fuente(rol), tuple) for rol in tm.ESCALA),
              f"los {len(tm.ESCALA)} papeles de la escala devuelven fuente")

    comprobar(tm.mezclar("#000000", "#ffffff", 0.5) == "#808080",
              "mezclar() interpola bien dos colores")
    comprobar(tm.contrario("oscuro") == "claro"
              and tm.contrario("claro") == "oscuro",
              "contrario() alterna los dos temas")


# --------------------------------------------------------------------
#  Nombres pedidos por cadena
# --------------------------------------------------------------------

# Donde se pide un papel tipografico y en que posicion del argumento.
# (funcion, indice del argumento)
USOS_ROL = {("fuente", 0), ("etiqueta", 2)}
# Los papeles de color llegan como 'tono', 'fondo' o por el metodo c().
USOS_COLOR = {("c", 0)}
MODULOS = ("gui.py", "asistente.py", "palabras.py", "widgets.py")


def literales(nodo) -> list[str]:
    """Las cadenas literales que se pasan a una llamada, por posicion."""
    return [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str)
            else None for a in nodo.args]


def recoger(nombre_archivo: str) -> tuple[set[str], set[str]]:
    """Papeles de letra y de color pedidos por su nombre en un fichero."""
    ruta = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), nombre_archivo)
    arbol = ast.parse(open(ruta, encoding="utf-8").read())

    roles: set[str] = set()
    colores: set[str] = set()
    for nodo in ast.walk(arbol):
        if not isinstance(nodo, ast.Call):
            continue
        funcion = getattr(nodo.func, "attr", getattr(nodo.func, "id", ""))
        args = literales(nodo)

        for nombre, indice in USOS_ROL:
            if funcion == nombre and len(args) > indice and args[indice]:
                roles.add(args[indice])
        for nombre, indice in USOS_COLOR:
            if funcion == nombre and len(args) > indice and args[indice]:
                colores.add(args[indice])

        # Los argumentos con nombre: rol="micro", tono="peligro", ...
        for clave in nodo.keywords:
            if not isinstance(clave.value, ast.Constant):
                continue
            valor = clave.value.value
            if not isinstance(valor, str):
                continue
            if clave.arg == "rol":
                roles.add(valor)
            elif clave.arg in ("tono", "fondo", "papel", "tono_borde"):
                colores.add(valor)
    return roles, colores


# Diccionarios cuyas claves son vocabulario interno del programa: se
# piden con una cadena desde otros modulos y tienen que poder escribirse
# con cualquier teclado. Los textos que ve el usuario si llevan tildes;
# estas claves, nunca.
def vocabularios() -> dict:
    import bandeja
    import config as cfg

    return {
        "tema.ESCALA": tm.ESCALA,
        "tema.PALETAS": tm.PALETAS,
        "tema.PALETAS['oscuro']": tm.PALETAS["oscuro"],
        "tema.PALETAS['claro']": tm.PALETAS["claro"],
        "tema.ESPACIO": tm.ESPACIO,
        "marca.VERSIONES": marca.VERSIONES,
        "config.NOMBRES_ESTILO": cfg.NOMBRES_ESTILO,
        "bandeja.ICONOS": bandeja.ICONOS,
    }


def probar_vocabulario() -> None:
    print("\nVOCABULARIO INTERNO\n" + "-" * 60)
    for nombre, diccionario in vocabularios().items():
        malas = [k for k in diccionario if not str(k).isascii()]
        comprobar(not malas,
                  f"{nombre}: {len(diccionario)} claves, todas ASCII"
                  + (f"  -> con tilde {malas}" if malas else ""))


def probar_nombres() -> None:
    print("\nNOMBRES PEDIDOS POR CADENA\n" + "-" * 60)

    validos_rol = set(tm.ESCALA)
    validos_color = set(tm.PALETAS[tm.POR_DEFECTO])

    for nombre in MODULOS:
        roles, colores = recoger(nombre)
        malos_rol = sorted(roles - validos_rol)
        malos_color = sorted(colores - validos_color)
        comprobar(not malos_rol,
                  f"{nombre}: {len(roles)} papeles de letra, todos existen"
                  + (f"  -> sobran {malos_rol}" if malos_rol else ""))
        comprobar(not malos_color,
                  f"{nombre}: {len(colores)} papeles de color, todos existen"
                  + (f"  -> sobran {malos_color}" if malos_color else ""))


# --------------------------------------------------------------------
#  Geometria de la marca
# --------------------------------------------------------------------

def probar_marca() -> None:
    print("\nMARCA\n" + "-" * 60)

    for version in marca.VERSIONES:
        piezas = marca.figuras(200, 100, version)
        dentro = all(-20 <= p.x0 and p.x1 <= 220 for p in piezas)
        censura = [p for p in piezas if p.papel == "censura"]
        comprobar(len(censura) == 1 and dentro,
                  f"version '{version}': {len(piezas)} figuras, una de censura")

    # El orden importa: el hueco se pinta antes que la barra que tapa.
    piezas = marca.figuras(200, 100, "completo")
    papeles = [p.papel for p in piezas]
    comprobar(papeles.index("aire") < papeles.index("censura"),
              "el hueco se dibuja antes que la barra de censura")

    comprobar(marca.version_para(200) == "completo"
              and marca.version_para(8) == "sello",
              "version_para() elige segun el tamano")


# --------------------------------------------------------------------
#  Edicion de listas
# --------------------------------------------------------------------

EJEMPLO = """\
# Cabecera que explica el formato
#   con dos lineas

#  --- insultos ---
cabron*
gilipollas

#  --- frases ---
me cago en todo
"""


def probar_listas() -> None:
    print("\nEDICION DE LISTAS\n" + "-" * 60)

    with tempfile.TemporaryDirectory() as carpeta:
        ruta = os.path.join(carpeta, "palabras.txt")
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(EJEMPLO)

        lista = listas.Lista(ruta)
        comprobar(lista.terminos() == ["cabron*", "gilipollas",
                                       "me cago en todo"],
                  "lee los terminos ignorando comentarios")

        lista.anadir("  NUEVA  Palabra  ")
        comprobar("nueva palabra" in lista.terminos(),
                  "al anadir normaliza espacios y mayusculas")

        objetivo = [e for e in lista.entradas() if e.texto == "gilipollas"][0]
        lista.cambiar(objetivo.linea, "gilipuertas")
        comprobar("gilipuertas" in lista.terminos()
                  and "gilipollas" not in lista.terminos(),
                  "edita el termino en su sitio")

        lista.quitar([e.linea for e in lista.entradas()
                      if e.texto == "cabron*"])
        comprobar("cabron*" not in lista.terminos(), "quita el termino pedido")

        lista.guardar()
        guardado = open(ruta, encoding="utf-8").read()
        comprobar(guardado.count("#") == EJEMPLO.count("#") + 1,
                  "conserva los comentarios y anade el apartado propio")
        comprobar("--- insultos ---" in guardado
                  and "--- frases ---" in guardado,
                  "conserva las categorias")
        comprobar(os.path.exists(ruta + ".bak"),
                  "deja copia de seguridad al guardar")

        import matcher
        comprobar(matcher.leer_lista(ruta) == listas.Lista(ruta).terminos(),
                  "el detector lee exactamente lo que se ha escrito")

    print()
    comprobar(listas.valido("hola") == "", "acepta un termino normal")
    for malo in ("", "   ", "# comentario", "*", "a*b"):
        comprobar(listas.valido(malo) != "",
                  f"rechaza {malo!r}")


# --------------------------------------------------------------------
#  Ventanas de verdad
# --------------------------------------------------------------------

def probar_ventanas() -> None:
    print("\nVENTANAS\n" + "-" * 60)

    import fuentes
    import sistema

    fuentes.preparar()
    sistema.preparar()

    import asistente
    import gui
    import palabras

    try:
        app = gui.Aplicacion()
    except Exception as error:  # noqa: BLE001
        comprobar(False, f"abrir la ventana principal: {error}")
        return

    # Que no salte la guia sola durante la prueba.
    app.config_app["asistente_visto"] = True

    try:
        for tema in ("oscuro", "claro"):
            if app.tema != tema:
                app._alternar_tema()

            guia = asistente.Asistente(app)
            pasos_ok = True
            for paso in range(len(guia.pasos)):
                try:
                    guia.paso = paso
                    guia._mostrar()
                    guia.update_idletasks()
                except Exception as error:  # noqa: BLE001
                    pasos_ok = False
                    print(f"         paso {paso + 1}: {error}")
            comprobar(pasos_ok, f"tema {tema}: los {len(guia.pasos)} pasos "
                                f"de la guia se dibujan")
            guia._cerrar_escucha()
            guia.destroy()

            try:
                editor = palabras.VentanaPalabras(app)
                editor.pestanas[0].var_busca.set("cab")
                editor.pestanas[0].refrescar()
                editor._cambiar_a(1)
                editor.update_idletasks()
                editor.destroy()
                comprobar(True, f"tema {tema}: el editor de listas abre")
            except Exception as error:  # noqa: BLE001
                comprobar(False, f"tema {tema}: el editor de listas: {error}")

            try:
                app._tick()
                comprobar(True, f"tema {tema}: el repaso periodico no falla")
            except Exception as error:  # noqa: BLE001
                comprobar(False, f"tema {tema}: el repaso periodico: {error}")
    finally:
        app.destroy()


def main() -> int:
    print("=" * 60)
    print("  BEEP STREAM  ·  pruebas de la interfaz")
    print("=" * 60)

    probar_tema()
    probar_vocabulario()
    probar_nombres()
    probar_marca()
    probar_listas()
    probar_ventanas()

    print()
    print("=" * 60)
    if fallos:
        print(f"  {len(fallos)} FALLO(S):")
        for texto in fallos:
            print(f"    - {texto}")
    else:
        print("  TODO CORRECTO")
    print("=" * 60 + "\n")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
