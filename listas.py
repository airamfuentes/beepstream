"""Edicion de palabras.txt y palabras_seguras.txt sin romperlos.

Los dos ficheros no son solo una lista: llevan una cabecera que explica
el formato y estan repartidos en categorias con comentarios. Reescribir
el fichero entero desde la lista de terminos borraria todo eso, y la
proxima vez que alguien lo abriera con el bloc de notas no entenderia
nada.

Aqui el fichero se guarda tal cual, linea a linea, marcando cuales son
terminos y cuales no. Editar cambia la linea en su sitio, borrar quita
esa linea y añadir la mete al final bajo un apartado propio. Los
comentarios y el orden de las categorias sobreviven.
"""

from __future__ import annotations

import os
import shutil
from typing import NamedTuple

# Encabezado del apartado donde van a parar las altas hechas desde la
# ventana. Se crea la primera vez que hace falta.
SECCION_PROPIA = "#  --- añadidas desde el programa ---"


class Entrada(NamedTuple):
    """Un termino y en que linea del fichero vive."""

    texto: str
    linea: int


def normalizar(texto: str) -> str:
    """Deja un termino como lo espera el detector.

    El detector compara en minusculas y con los espacios justos. Se
    normaliza al entrar para que no haya dos versiones de la misma
    palabra separadas solo por un espacio de mas.
    """
    return " ".join(texto.strip().lower().split())


def valido(texto: str) -> str:
    """Devuelve el motivo por el que un termino no vale, o "" si vale."""
    limpio = normalizar(texto)
    if not limpio:
        return "No puede estar vacío."
    if limpio.startswith("#"):
        return "No puede empezar por #: esa es la marca de los comentarios."
    if "\n" in texto or "\r" in texto:
        return "Tiene que caber en una sola línea."
    if limpio.count("*") > 1 or ("*" in limpio and not limpio.endswith("*")):
        return "El asterisco solo vale al final, para marcar una raíz."
    if limpio == "*":
        return "Una raíz vacía censuraría absolutamente todo."
    return ""


class Lista:
    """Un fichero de terminos, con sus comentarios intactos."""

    def __init__(self, ruta: str) -> None:
        self.ruta = ruta
        self._lineas: list[str] = []
        self.cargar()

    # --- lectura ----------------------------------------------------

    def cargar(self) -> None:
        try:
            with open(self.ruta, "r", encoding="utf-8") as fichero:
                self._lineas = fichero.read().splitlines()
        except OSError:
            self._lineas = []

    @staticmethod
    def _es_termino(linea: str) -> bool:
        limpia = linea.strip()
        return bool(limpia) and not limpia.startswith("#")

    def entradas(self) -> list[Entrada]:
        """Los terminos del fichero, en el orden en el que estan."""
        return [
            Entrada(normalizar(linea), i)
            for i, linea in enumerate(self._lineas)
            if self._es_termino(linea)
        ]

    def terminos(self) -> list[str]:
        return [e.texto for e in self.entradas()]

    def contiene(self, texto: str, salvo: int | None = None) -> bool:
        objetivo = normalizar(texto)
        return any(e.texto == objetivo and e.linea != salvo
                   for e in self.entradas())

    # --- escritura --------------------------------------------------

    def anadir(self, texto: str) -> int:
        """Mete un termino al final, en el apartado propio. Da su linea."""
        limpio = normalizar(texto)
        if SECCION_PROPIA not in self._lineas:
            if self._lineas and self._lineas[-1].strip():
                self._lineas.append("")
            self._lineas.append(SECCION_PROPIA)
        self._lineas.append(limpio)
        return len(self._lineas) - 1

    def cambiar(self, linea: int, texto: str) -> None:
        """Reescribe un termino donde estaba, sin moverlo de categoria."""
        if 0 <= linea < len(self._lineas):
            self._lineas[linea] = normalizar(texto)

    def quitar(self, lineas: list[int]) -> None:
        """Borra varios terminos de una vez.

        Se marcan y luego se barren de atras adelante: borrando sobre la
        marcha, cada eliminacion desplazaria los indices siguientes.
        """
        for numero in sorted(set(lineas), reverse=True):
            if 0 <= numero < len(self._lineas):
                del self._lineas[numero]

    def guardar(self) -> None:
        """Escribe el fichero, dejando antes una copia de seguridad.

        La copia (.bak) es barata y cubre el unico fallo caro de este
        editor: vaciar la lista sin querer justo antes de emitir.
        """
        if os.path.exists(self.ruta):
            try:
                shutil.copy2(self.ruta, self.ruta + ".bak")
            except OSError:
                pass  # sin copia, pero se guarda igual

        # Se escribe a un temporal y se renombra: si algo falla a mitad,
        # el fichero bueno sigue donde estaba.
        temporal = self.ruta + ".tmp"
        with open(temporal, "w", encoding="utf-8", newline="\n") as fichero:
            fichero.write("\n".join(self._lineas).rstrip("\n") + "\n")
        os.replace(temporal, self.ruta)
