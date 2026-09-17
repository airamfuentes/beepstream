"""Resolucion y apertura de dispositivos de audio.

Windows expone cada tarjeta varias veces, una por cada API de sonido
(MME, DirectSound, WASAPI, WDM-KS). Eso trae dos problemas.

El primero es que buscar "CABLE Input" no devuelve uno sino tres, y
PortAudio entonces se niega a elegir:

    ValueError: Multiple output devices found for 'CABLE Input'

El segundo es que no todas las copias funcionan igual. Un mismo
microfono puede abrirse por WASAPI y fallar por DirectSound con

    Unanticipated host error [PaErrorCode -9999]

sobre todo si es un casco inalambrico que se ha dormido, o si otro
programa lo tiene cogido. Por eso al abrir no se prueba una sola copia:
se prueban todas las del mismo aparato, de mejor API a peor, y solo se
da error si fallan todas.
"""

from __future__ import annotations

import sounddevice as sd

# De mejor a peor. WDM-KS queda fuera a proposito: es exclusivo, choca
# con cualquier otro programa que use el micro y casi nunca funciona
# mientras OBS esta abierto.
PREFERENCIA_API = ("Windows WASAPI", "MME", "Windows DirectSound")

# MME recorta los nombres a 31 caracteres, asi que para saber si dos
# entradas son el mismo aparato se comparan solo los primeros.
_LARGO_COMPARACION = 28


def _nombre_api(indice_api: int) -> str:
    try:
        return sd.query_hostapis(indice_api)["name"]
    except Exception:  # noqa: BLE001
        return "?"


def _orden_api(nombre_api: str) -> int:
    try:
        return PREFERENCIA_API.index(nombre_api)
    except ValueError:
        return len(PREFERENCIA_API)


def describir(indice) -> str:
    """Nombre legible de un dispositivo, con su API entre corchetes."""
    if indice is None:
        return "(predeterminado del sistema)"
    try:
        d = sd.query_devices(indice)
    except Exception:  # noqa: BLE001
        return f"indice {indice}"
    return f"{d['name']}  [{_nombre_api(d['hostapi'])}]"


def mismo_aparato(a: str, b: str) -> bool:
    """Si dos nombres de dispositivo son el mismo aparato."""
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return False
    corto, largo = (a, b) if len(a) <= len(b) else (b, a)
    return largo.startswith(corto[:_LARGO_COMPARACION])


def candidatos(nombre: str, entrada: bool) -> list[int]:
    """Indices de los dispositivos cuyo nombre contiene `nombre`."""
    buscado = nombre.lower().strip()
    clave = "max_input_channels" if entrada else "max_output_channels"
    return [
        i
        for i, d in enumerate(sd.query_devices())
        if d[clave] > 0 and buscado in d["name"].lower()
    ]


def resolver(dispositivo, entrada: bool):
    """Convierte lo que haya en config.json en un indice concreto.

    Acepta None (dispositivo por defecto del sistema), un indice ya
    numerico, o un nombre parcial como "CABLE Input".
    """
    if dispositivo is None:
        return None
    if isinstance(dispositivo, int):
        return dispositivo
    texto = str(dispositivo).strip()
    if texto.isdigit():
        return int(texto)

    encontrados = candidatos(texto, entrada)
    if not encontrados:
        tipo = "entrada" if entrada else "salida"
        raise ValueError(
            f"No hay ningun dispositivo de {tipo} que se llame '{texto}'.\n"
            f"Ejecuta  py -3.11 main.py --listar  para ver los disponibles."
        )

    for api in PREFERENCIA_API:
        for indice in encontrados:
            if _nombre_api(sd.query_devices(indice)["hostapi"]) == api:
                return indice
    return encontrados[0]


def alternativas(indice, entrada: bool) -> list:
    """El mismo aparato en todas las APIs, empezando por el pedido.

    Devuelve una lista de indices para ir probando en orden. Si el
    dispositivo pedido falla, el siguiente suele ser el mismo microfono
    por otra API, que a menudo si abre.
    """
    if indice is None:
        return [None]

    # Puede llegar un nombre ("CABLE Input") en vez de un indice: hay que
    # concretarlo antes, o query_devices se queja de ambiguedad.
    try:
        indice = resolver(indice, entrada)
    except ValueError:
        return [indice]

    try:
        objetivo = sd.query_devices(indice)["name"]
    except Exception:  # noqa: BLE001
        return [indice]

    clave = "max_input_channels" if entrada else "max_output_channels"
    hermanos = []
    for i, d in enumerate(sd.query_devices()):
        if i == indice or d[clave] <= 0:
            continue
        if mismo_aparato(objetivo, d["name"]):
            hermanos.append((_orden_api(_nombre_api(d["hostapi"])), i))

    hermanos.sort()
    # El pedido va primero: si funciona, se respeta la eleccion del usuario.
    return [indice] + [i for _, i in hermanos]


def mejor_api(indice, entrada: bool):
    """El mismo aparato, pero por la API mas fiable disponible.

    Windows suele dar como predeterminado el endpoint de DirectSound,
    que es el mas propenso a fallar con "Unanticipated host error". Si
    existe la copia por WASAPI del mismo microfono, se prefiere esa.
    """
    if indice is None:
        return None
    opciones = alternativas(indice, entrada)
    if not opciones:
        return indice
    return min(
        opciones,
        key=lambda i: _orden_api(_nombre_api(sd.query_devices(i)["hostapi"])),
    )


def abrir(constructor, indice, entrada: bool, que_es: str):
    """Abre un flujo probando el dispositivo y sus copias en otras APIs.

    `constructor` recibe un indice y devuelve el stream ya creado. Se
    prueba a arrancarlo de verdad, porque muchos fallos de PortAudio no
    aparecen hasta el start().

    Devuelve (stream, indice_usado). Si ninguno abre, lanza RuntimeError
    con un mensaje que explica que mirar.
    """
    intentos = alternativas(indice, entrada)
    fallos = []

    for candidato in intentos:
        flujo = None
        try:
            flujo = constructor(candidato)
            flujo.start()
            return flujo, candidato
        except Exception as error:  # noqa: BLE001
            if flujo is not None:
                try:
                    flujo.close()
                except Exception:  # noqa: BLE001
                    pass
            fallos.append((candidato, str(error).split("\n")[0]))

    detalle = "\n".join(
        f"    - {describir(i)}\n        {mensaje}" for i, mensaje in fallos
    )
    aparato = describir(indice)
    raise RuntimeError(
        f"No se puede abrir {que_es}:\n\n    {aparato}\n\n"
        f"Se ha intentado por todas las APIs de Windows:\n{detalle}\n\n"
        "Causas mas frecuentes, por orden:\n"
        "  1. Si es un casco inalambrico, esta apagado o dormido.\n"
        "     Enciendelo y espera a que Windows lo reconozca.\n"
        "  2. Otro programa lo tiene cogido en exclusiva.\n"
        "     Cierra OBS o Discord y vuelve a intentarlo.\n"
        "  3. Windows no da permiso: Configuracion > Privacidad y\n"
        "     seguridad > Microfono > permitir a las aplicaciones de\n"
        "     escritorio acceder al microfono.\n"
        "  4. El dispositivo esta desactivado en el Panel de control\n"
        "     de Sonido."
    )


def listar(entrada: bool) -> list[tuple[int, str]]:
    """Dispositivos disponibles como (indice, nombre con API).

    Se ordenan poniendo delante los de la API preferida, para que lo
    primero que vea el usuario en el desplegable sea lo que conviene
    elegir. Los de WDM-KS se dejan fuera: son exclusivos y chocan con
    OBS.
    """
    clave = "max_input_channels" if entrada else "max_output_channels"
    salida = []
    for i, d in enumerate(sd.query_devices()):
        if d[clave] <= 0:
            continue
        api = _nombre_api(d["hostapi"])
        if api in ("Windows WDM-KS", "ASIO"):
            continue
        salida.append((_orden_api(api), i, f"{d['name']}  [{api}]"))

    salida.sort(key=lambda x: (x[0], x[1]))
    return [(i, nombre) for _, i, nombre in salida]


def refrescar() -> None:
    """Vuelve a preguntarle a Windows que dispositivos hay.

    PortAudio construye su lista al arrancar y no la revisa nunca mas,
    asi que un VB-CABLE recien instalado no aparece hasta reiniciar el
    programa. Cerrando y reabriendo la libreria se vuelve a leer, que es
    lo que necesita la guia de instalacion para poder decir "ya esta"
    sin obligar a reiniciar.

    No se puede hacer con flujos de audio abiertos: los deja invalidos.
    """
    sd._terminate()
    sd._initialize()
