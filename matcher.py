"""Deteccion de palabras y frases prohibidas en texto reconocido.

El problema real no es buscar una palabra en una cadena: es que Vosk
transcribe fonetica, no ortografia. Si dices "gilipollas" el modelo
pequeno puede escribir "gilipoyas", "gili pollas" o "jilipollas", y una
comparacion literal dejaria pasar el insulto a TikTok.

La solucion es reducir cada palabra a una CLAVE FONETICA: una forma
canonica donde todas las grafias que suenan igual en espanol colapsan al
mismo texto. Se compara clave contra clave.

Lo importante es que la reduccion sea agresiva con lo que de verdad suena
igual (ll/y, b/v, c/k/qu, h muda, seseo) y conservadora con lo que NO
suena igual. Tres casos que rompen implementaciones ingenuas:

    coño   -> koño    cono  -> kono     distintos (la n con virgulilla)
    chocho -> CoCo    coco  -> koko     distintos (ch no es c + h)
    forro  -> foRo    foro  -> foro     distintos (rr no es r repetida)

Si se colapsa cualquiera de los tres, el censor pita encima de palabras
corrientes. De ahi que la ene, la che y la erre se protejan antes de
tocar nada.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

# Marcadores internos para sonidos que deben sobrevivir a la
# normalizacion. Se eligen fuera del rango a-z para que ninguna regla
# posterior los toque por accidente.
_MARCA_ENYE = "\x01"
_MARCA_CHE = "\x02"
_MARCA_ERRE = "\x03"

_SOLO_LETRAS = re.compile(r"[^a-zñ]")
# Compiladas una sola vez. re.sub() con el patron en texto tiene que
# pasar por la tabla de patrones compilados en CADA llamada, y por
# aqui se pasa tres veces por cada palabra reconocida.
_SESEO = re.compile(r"c([ei])")
_GE_GI = re.compile(r"g([ei])")
_DOBLES = re.compile(r"(.)\1+")

# Longitud minima para arriesgarse a comparar por parecido en modo
# agresivo. Por debajo de esto una sola letra de diferencia separa
# demasiadas palabras corrientes ("mierda"/"pierda", "puta"/"pata").
MINIMO_PARA_PARECIDO = 7


def _quitar_tildes(texto: str) -> str:
    """Quita diacriticos preservando la ene con virgulilla.

    unicodedata la descompone en "n" + tilde combinante, asi que sin
    proteccion previa "coño" acabaria siendo "cono".
    """
    texto = texto.replace("ñ", _MARCA_ENYE).replace("Ñ", _MARCA_ENYE)
    descompuesto = unicodedata.normalize("NFD", texto)
    sin_marcas = "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")
    return sin_marcas.replace(_MARCA_ENYE, "ñ")


@lru_cache(maxsize=4096)
def clave_fonetica(palabra: str) -> str:
    """Reduce una palabra a su forma canonica por sonido.

    Devuelve "" si la palabra no contiene letras utiles.

    Va memorizada porque el resultado depende solo de la palabra y
    sale caro: quitar tildes, tres pasadas de expresion regular y
    una docena de sustituciones. Hablando se repiten sin parar las
    mismas palabras y el vocabulario del modelo esta acotado, asi
    que la cache acierta casi siempre y ocupa unos kilobytes.
    """
    p = _quitar_tildes(palabra.lower())
    p = _SOLO_LETRAS.sub("", p)
    if not p:
        return ""

    # 1. Digrafos que deben tratarse como una sola consonante, antes de
    #    que las reglas de letra suelta los desarmen.
    p = p.replace("ch", _MARCA_CHE)
    p = p.replace("ll", "y")  # ll e y ya son el mismo sonido: yeismo

    # 2. La h es muda en espanol (la ch ya esta a salvo arriba).
    p = p.replace("qu", "k")
    p = p.replace("h", "")

    # 3. Pares que suenan identicos.
    p = p.replace("v", "b").replace("w", "b")
    p = p.replace("z", "s")
    p = _SESEO.sub(r"s\1", p)  # seseo: ce/ci -> se/si
    p = p.replace("c", "k")  # el resto de c es sonido k
    p = _GE_GI.sub(r"j\1", p)  # ge/gi suenan como je/ji
    p = p.replace("x", "s")

    # 4. La rr es un fonema propio, no una r repetida: "pero" y "perro"
    #    son palabras distintas. Se protege antes de colapsar dobles, o
    #    "forro" acabaria valiendo lo mismo que "foro".
    p = p.replace("rr", _MARCA_ERRE)
    p = _DOBLES.sub(r"\1", p)

    # 5. Plural. Se hace en los dos lados de la comparacion, asi que
    #    "cabrones" y "cabron" acaban en la misma clave.
    if p.endswith("es") and len(p) > 4:
        p = p[:-2]
    elif p.endswith("s") and len(p) > 3:
        p = p[:-1]

    return p.replace(_MARCA_CHE, "C").replace(_MARCA_ERRE, "R")


def _difieren_en_una(a: str, b: str) -> bool:
    """True si de `a` a `b` hay como mucho una letra de diferencia.

    Equivale a una distancia de edicion de 1, pero sin construir la
    matriz completa: basta con localizar la primera discrepancia y
    comprobar que lo que queda detras coincide.
    """
    largo_a, largo_b = len(a), len(b)
    if abs(largo_a - largo_b) > 1:
        return False
    if a == b:
        return True

    if largo_a > largo_b:  # trabajar siempre con la corta en `a`
        a, b, largo_a, largo_b = b, a, largo_b, largo_a

    i = 0
    while i < largo_a and a[i] == b[i]:
        i += 1

    if largo_a == largo_b:  # sustitucion de una letra
        return a[i + 1 :] == b[i + 1 :]
    return a[i:] == b[i + 1 :]  # sobra una letra en la larga


@dataclass(frozen=True)
class PalabraReconocida:
    """Una palabra con su posicion temporal en el audio, tal y como la
    devuelve Vosk. Los tiempos son segundos desde el inicio del stream."""

    texto: str
    inicio: float
    fin: float
    confianza: float = 1.0


@dataclass(frozen=True)
class Coincidencia:
    """Un tramo de audio que hay que tapar con el beep."""

    termino: str  # la entrada de palabras.txt que ha saltado
    dicho: str  # lo que Vosk transcribio realmente
    inicio: float
    fin: float

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio


class Detector:
    """Compara la transcripcion contra la lista de terminos prohibidos.

    Un termino puede ser:

      - una palabra           cabron
      - una frase             vete a la mierda
      - una raiz con comodin  cabron*   (cubre cabronazo, cabronada...)

    Las frases se comparan sobre ventanas de N palabras consecutivas,
    priorizando siempre la coincidencia mas larga: si dices "hijo de
    puta" queremos tapar las tres palabras, no solo "puta".
    """

    def __init__(
        self,
        terminos: list[str],
        modo: str = "balanceado",
        seguras: list[str] | None = None,
    ) -> None:
        self.modo = modo
        self._por_clave: dict[str, str] = {}
        self._prefijos: list[tuple[str, str]] = []
        self._para_parecido: list[tuple[str, str]] = []
        self._max_palabras = 1
        # Lista blanca: manda sobre todo lo demas. Es la valvula de
        # escape cuando una raiz o el modo agresivo pillan de mas, y
        # evita tener que desactivar el termino entero.
        #
        # Admite frases ademas de palabras, porque el espanol esta lleno
        # de expresiones que llevan dentro una palabra fea sin serlo:
        # "se quedo tan pancho" no es un insulto aunque "pancho" lo sea.
        self._seguras: set[str] = set()
        self._frases_seguras: list[list[str]] = []
        for entrada in seguras or []:
            claves = [c for c in (clave_fonetica(t) for t in entrada.split()) if c]
            if not claves:
                continue
            if len(claves) == 1:
                self._seguras.add(claves[0])
            else:
                self._frases_seguras.append(claves)
        self._max_seguras = max(
            (len(f) for f in self._frases_seguras), default=1
        )
        self._cargar(terminos)

    @property
    def total_terminos(self) -> int:
        return len(set(self._por_clave.values()) | {t for _, t in self._prefijos})

    def _cargar(self, terminos: list[str]) -> None:
        for termino in terminos:
            crudo = termino.strip()
            if not crudo:
                continue

            # Un asterisco final convierte el termino en una raiz: basta
            # con que la palabra dicha empiece asi.
            es_raiz = crudo.endswith("*")
            limpio = crudo.rstrip("*").strip()

            tokens = [t for t in limpio.split() if t]
            claves = [clave_fonetica(t) for t in tokens]
            claves = [c for c in claves if c]
            if not claves:
                continue

            if es_raiz:
                # El comodin solo tiene sentido sobre una palabra suelta.
                self._prefijos.append(("".join(claves), crudo))
                continue

            self._max_palabras = max(self._max_palabras, len(claves))

            # Se indexan dos formas: con separacion y pegada. Asi
            # "hijoputa" tambien salta si Vosk lo parte en "hijo puta",
            # y viceversa.
            for clave in (" ".join(claves), "".join(claves)):
                self._por_clave.setdefault(clave, crudo)

            if len(claves) == 1 and len(claves[0]) >= MINIMO_PARA_PARECIDO:
                self._para_parecido.append((claves[0], crudo))

    def _termino_de(self, claves: list[str]) -> str | None:
        """`claves` son las claves foneticas de la ventana, ya calculadas.

        Se reciben hechas en vez de calcularlas aqui porque `buscar`
        prueba la misma palabra dentro de varias ventanas y antes se
        volvia a reducir en cada una: para una frase de catorce palabras
        eran 276 reducciones para catorce palabras distintas.
        """
        if not all(claves):
            return None

        # La lista blanca se consulta antes que nada: una palabra
        # declarada segura no se censura por ninguna via.
        if len(claves) == 1 and claves[0] in self._seguras:
            return None

        if self.modo == "estricto" and len(claves) == 1:
            # En estricto no se admite la variante pegada de una sola
            # palabra: solo la coincidencia directa.
            return self._por_clave.get(claves[0])

        # Con una sola palabra la variante separada y la pegada son la
        # misma cadena: no hay que buscarla dos veces.
        if len(claves) == 1:
            candidatas = (claves[0],)
        else:
            candidatas = (" ".join(claves), "".join(claves))
        for candidata in candidatas:
            termino = self._por_clave.get(candidata)
            if termino is not None:
                return termino

        if self.modo == "estricto":
            return None

        # Raices con comodin: "cabron*" tapa cabronazo y cabronada.
        #
        # Solo sobre UNA palabra. Aplicarlo a la clave concatenada de una
        # ventana haria que "capull*" tapase "capullo de la rosa se"
        # entero, porque la concatenacion tambien empieza por "kapuy".
        if len(claves) == 1:
            for prefijo, termino in self._prefijos:
                if claves[0].startswith(prefijo):
                    return termino

        # Modo agresivo: una letra de diferencia, solo en palabras largas
        # donde eso no confunde terminos corrientes.
        if self.modo == "agresivo" and len(claves) == 1:
            dicha = claves[0]
            if len(dicha) >= MINIMO_PARA_PARECIDO:
                for clave, termino in self._para_parecido:
                    if _difieren_en_una(dicha, clave):
                        return termino

        return None

    def _salto_seguro(self, claves: list[str], i: int) -> int:
        """Cuantas palabras saltar si aqui empieza una frase protegida.

        Devuelve 0 si no hay ninguna. Se comprueba antes de buscar
        insultos, asi que una expresion de la lista blanca gana aunque
        contenga una palabra prohibida.
        """
        if not self._frases_seguras:
            return 0
        tope = min(self._max_seguras, len(claves) - i)
        for n in range(tope, 1, -1):
            if claves[i : i + n] in self._frases_seguras:
                return n
        return 0

    def buscar(self, palabras: list[PalabraReconocida]) -> list[Coincidencia]:
        """Devuelve todos los tramos a censurar de una transcripcion.

        Recorre de izquierda a derecha probando primero las ventanas mas
        largas. Al encontrar una coincidencia salta por encima de ella,
        de modo que las palabras ya tapadas no vuelven a evaluarse.
        """
        encontradas: list[Coincidencia] = []
        i = 0
        total = len(palabras)
        # Una sola reduccion fonetica por palabra para toda la busqueda.
        claves = [clave_fonetica(p.texto) for p in palabras]

        while i < total:
            protegidas = self._salto_seguro(claves, i)
            if protegidas:
                i += protegidas
                continue

            avance = 1
            for n in range(min(self._max_palabras, total - i), 0, -1):
                termino = self._termino_de(claves[i : i + n])
                if termino is None:
                    continue
                ventana = palabras[i : i + n]
                encontradas.append(
                    Coincidencia(
                        termino=termino,
                        dicho=" ".join(p.texto for p in ventana),
                        inicio=ventana[0].inicio,
                        fin=ventana[-1].fin,
                    )
                )
                avance = n
                break
            i += avance

        return encontradas


def fusionar(coincidencias: list[Coincidencia]) -> list[Coincidencia]:
    """Une las coincidencias que se pisan en el tiempo.

    Hace falta porque Vosk va corrigiendo los tiempos: la misma palabra
    aparece primero en un resultado parcial y despues en el final, con el
    fin ajustado unos milisegundos. Sin fusionar, se contaria dos veces.
    """
    resultado: list[Coincidencia] = []
    for actual in sorted(coincidencias, key=lambda c: (c.inicio, c.fin)):
        if resultado and actual.inicio < resultado[-1].fin:
            previa = resultado[-1]
            resultado[-1] = Coincidencia(
                termino=previa.termino,
                dicho=previa.dicho,
                inicio=previa.inicio,
                fin=max(previa.fin, actual.fin),
            )
        else:
            resultado.append(actual)
    return resultado


def leer_lista(ruta: str) -> list[str]:
    """Lee palabras.txt ignorando comentarios y lineas vacias."""
    terminos: list[str] = []
    with open(ruta, "r", encoding="utf-8") as fichero:
        for linea in fichero:
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            terminos.append(linea.lower())
    return terminos


def leer_seguras(ruta: str) -> list[str]:
    """Lee la lista blanca. Si no existe, no pasa nada: se trabaja sin ella."""
    try:
        return leer_lista(ruta)
    except OSError:
        return []
