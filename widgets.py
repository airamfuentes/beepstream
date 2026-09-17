"""Piezas de interfaz con el tema aplicado.

Tkinter no trae nada parecido a un sistema de componentes: cada widget
se pinta a mano y no sabe nada de temas. Aqui esta esa capa, para que la
ventana principal y el asistente de primer arranque se vean iguales y
cambien de claro a oscuro a la vez.

El trato es el mismo en todas las piezas: se crean a traves de un `Kit`,
que apunta que color lleva cada opcion de cada widget. Cuando se cambia
de tema, el kit recorre esa lista y reescribe los colores. Ningun sitio
del programa escribe un "#101013" a mano.
"""

from __future__ import annotations

import ctypes
import math
import sys
import tkinter as tk
from tkinter import ttk

import marca
import tema as tm


def pill(lienzo: tk.Canvas, x0, y0, x1, y1, color, **kw) -> int:
    """Rectangulo de puntas redondeadas sobre un lienzo.

    El lienzo de Tkinter no dibuja rectangulos redondeados, pero si
    lineas con la punta redonda: una linea del grosor del lado corto es
    exactamente la figura que hace falta, y con mejor suavizado que una
    aproximacion con arcos.
    """
    ancho, alto = x1 - x0, y1 - y0
    if ancho <= alto:
        grosor = max(int(round(ancho)), 1)
        medio = grosor / 2.0
        return lienzo.create_line(x0 + medio, y0 + medio, x0 + medio, y1 - medio,
                                  width=grosor, fill=color, capstyle="round", **kw)
    grosor = max(int(round(alto)), 1)
    medio = grosor / 2.0
    return lienzo.create_line(x0 + medio, y0 + medio, x1 - medio, y0 + medio,
                              width=grosor, fill=color, capstyle="round", **kw)


def barra_de_titulo(ventana: tk.Misc, oscura: bool) -> None:
    """Pone la barra de titulo de Windows a juego con el tema.

    Tk no la dibuja: la dibuja Windows, y por defecto siempre en claro.
    Queda una franja blanca encima de una ventana negra. DWM tiene un
    atributo para cambiarla, y desde Windows 10 20H1 es el 20 (antes era
    el 19, y en versiones anteriores no existe).

    Hay que llamarlo con la ventana ya dibujada o Windows lo ignora.
    """
    if sys.platform != "win32":
        return
    try:
        ventana.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(ventana.winfo_id())
        valor = ctypes.c_int(1 if oscura else 0)
        for atributo in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, atributo, ctypes.byref(valor),
                    ctypes.sizeof(valor)) == 0:
                return
    except Exception:  # noqa: BLE001
        pass  # Windows antiguo: se queda con la barra clara


def redondeado(lienzo: tk.Canvas, x0, y0, x1, y1, radio, **kw) -> int:
    """Rectangulo de esquinas redondeadas sobre un lienzo.

    Se dibuja como un poligono con los vertices duplicados en las
    esquinas y suavizado activado: el trazador de curvas de Tk redondea
    justo esos puntos y deja rectos los lados.
    """
    puntos = [
        x0 + radio, y0, x1 - radio, y0, x1, y0,
        x1, y0 + radio, x1, y1 - radio, x1, y1,
        x1 - radio, y1, x0 + radio, y1, x0, y1,
        x0, y1 - radio, x0, y0 + radio, x0, y0,
    ]
    return lienzo.create_polygon(puntos, smooth=True, **kw)


class Kit:
    """Fabrica de widgets que recuerda con que color se pinto cada uno."""

    def __init__(self, raiz: tk.Misc, nombre_tema: str = tm.POR_DEFECTO) -> None:
        self.raiz = raiz
        self.tema = nombre_tema
        self.color = tm.paleta(nombre_tema)
        self._pintados: list[tuple[tk.Misc, dict]] = []
        self._al_cambiar: list = []
        # Ventanas cuya barra de titulo hay que repintar al cambiar de
        # tema. Las dibuja Windows, no Tk, y no se enteran solas.
        self._ventanas: list[tk.Misc] = []

    # --- color ------------------------------------------------------

    def c(self, papel: str) -> str:
        return self.color[papel]

    def registrar(self, widget, **papeles):
        """Apunta que papel cumple cada opcion del widget y lo pinta."""
        self._pintados.append((widget, papeles))
        self._aplicar(widget, papeles)
        return widget

    def _aplicar(self, widget, papeles: dict) -> None:
        for opcion, papel in papeles.items():
            try:
                widget.configure(**{opcion: self.color[papel]})
            except tk.TclError:
                pass  # el widget ya no existe o no admite esa opcion

    def adoptar_ventana(self, ventana: tk.Misc) -> None:
        """Pone la barra de titulo de esa ventana a juego, ahora y al
        cambiar de tema."""
        self._ventanas.append(ventana)
        barra_de_titulo(ventana, self.tema == "oscuro")

    def al_cambiar_tema(self, funcion) -> None:
        """Registra algo que hay que repintar a mano (lienzos, sobre todo)."""
        self._al_cambiar.append(funcion)

    def cambiar_tema(self, nombre: str) -> None:
        self.tema = nombre
        self.color = tm.paleta(nombre)
        self.estilos_ttk()
        vivos = []
        for widget, papeles in self._pintados:
            try:
                widget.winfo_exists()
            except tk.TclError:
                continue
            self._aplicar(widget, papeles)
            vivos.append((widget, papeles))
        self._pintados = vivos

        vivas = []
        for ventana in self._ventanas:
            try:
                ventana.winfo_exists()
            except tk.TclError:
                continue
            barra_de_titulo(ventana, nombre == "oscuro")
            vivas.append(ventana)
        self._ventanas = vivas

        for funcion in self._al_cambiar:
            funcion()

    # --- ttk --------------------------------------------------------

    def estilos_ttk(self) -> None:
        """Deja los desplegables planos y del color del tema.

        El tema "clam" es el unico de los que trae Tk que deja cambiar
        los colores de verdad; los nativos ignoran casi todo.
        """
        estilo = ttk.Style(self.raiz)
        estilo.theme_use("clam")
        # clam dibuja el desplegable con seis colores distintos: el campo,
        # el boton de la flecha y los cuatro bordes con los que finge
        # relieve. Si solo se cambia el campo queda un marco claro
        # alrededor y un boton gris al lado. Hay que igualarlos todos.
        plano = dict(
            fieldbackground=self.c("panel_alto"),
            background=self.c("panel_alto"),
            foreground=self.c("texto"),
            bordercolor=self.c("panel_alto"),
            lightcolor=self.c("panel_alto"),
            darkcolor=self.c("panel_alto"),
            selectbackground=self.c("panel_alto"),
            selectforeground=self.c("texto"),
            arrowcolor=self.c("suave"),
        )
        estilo.configure("BS.TCombobox", borderwidth=0, relief="flat",
                         arrowsize=13, padding=(10, 7), **plano)
        estilo.map(
            "BS.TCombobox",
            fieldbackground=[("readonly", self.c("panel_alto")),
                             ("disabled", self.c("panel"))],
            background=[("readonly", self.c("panel_alto")),
                        ("active", self.c("borde")),
                        ("disabled", self.c("panel"))],
            foreground=[("readonly", self.c("texto")),
                        ("disabled", self.c("apagado"))],
            arrowcolor=[("disabled", self.c("apagado")),
                        ("active", self.c("texto"))],
            bordercolor=[("focus", self.c("borde_vivo")),
                         ("disabled", self.c("panel"))],
            lightcolor=[("focus", self.c("panel_alto")),
                        ("disabled", self.c("panel"))],
            darkcolor=[("focus", self.c("panel_alto")),
                       ("disabled", self.c("panel"))])

        # clam monta la barra con dos flechas y un relieve falso. Se le
        # cambia la plantilla para dejar solo el carril y el pulgar: una
        # barra fina sin adornos, que es lo que pide el resto.
        try:
            estilo.layout("BS.Vertical.TScrollbar", [
                ("Vertical.Scrollbar.trough", {
                    "sticky": "ns",
                    "children": [("Vertical.Scrollbar.thumb",
                                  {"expand": "1", "sticky": "nswe"})]})])
        except tk.TclError:
            pass
        estilo.configure(
            "BS.Vertical.TScrollbar", background=self.c("apagado"),
            troughcolor=self.c("fondo"), bordercolor=self.c("fondo"),
            lightcolor=self.c("fondo"), darkcolor=self.c("fondo"),
            borderwidth=0, relief="flat", width=8)
        estilo.map("BS.Vertical.TScrollbar",
                   background=[("active", self.c("tenue")),
                               ("!active", self.c("apagado"))])

        # La lista que se despliega es una ventana aparte de Tk y no
        # hereda el estilo ttk: se configura por la base de opciones.
        for opcion, papel in (("background", "panel_alto"),
                              ("foreground", "texto"),
                              ("selectBackground", "tinta"),
                              ("selectForeground", "sobre_tinta")):
            self.raiz.option_add(f"*TCombobox*Listbox.{opcion}", self.c(papel))

    # --- piezas -----------------------------------------------------

    def marco(self, padre, papel: str = "panel", **kw) -> tk.Frame:
        return self.registrar(tk.Frame(padre, **kw), bg=papel)

    def etiqueta(self, padre, texto: str = "", rol: str = "cuerpo",
                 tono: str = "texto", fondo: str = "panel", **kw) -> tk.Label:
        return self.registrar(
            tk.Label(padre, text=texto, font=tm.fuente(rol), **kw),
            bg=fondo, fg=tono)

    def separador(self, padre, fondo: str = "panel") -> tk.Frame:
        linea = self.registrar(tk.Frame(padre, height=1), bg="borde")
        return linea

    def combo(self, padre, **kw) -> ttk.Combobox:
        combo = ttk.Combobox(padre, state="readonly", style="BS.TCombobox",
                             font=tm.fuente("cuerpo"), **kw)
        # El cursor de texto sobra en un desplegable de solo lectura.
        combo.configure(cursor="hand2")
        return combo


class Desplazable(tk.Frame):
    """Zona con barra de desplazamiento vertical.

    Tkinter no tiene contenedor con scroll: el unico widget que se puede
    desplazar es el lienzo, asi que se mete dentro un marco normal y se
    le mueve la ventana de dibujo. Lo de fuera queda quieto (cabecera y
    botones) y solo se desplaza esto.

    La barra solo aparece cuando de verdad sobra contenido: en una
    ventana grande no hay nada que desplazar y una barra vacia solo
    estorba.
    """

    def __init__(self, padre, kit: Kit, papel: str = "fondo") -> None:
        super().__init__(padre, bd=0, highlightthickness=0)
        kit.registrar(self, bg=papel)
        self.kit = kit

        self.barra = ttk.Scrollbar(self, orient="vertical",
                                   style="BS.Vertical.TScrollbar")
        self.lienzo = tk.Canvas(self, highlightthickness=0, bd=0,
                                yscrollcommand=self._mover_barra)
        kit.registrar(self.lienzo, bg=papel)
        self.lienzo.pack(side="left", fill="both", expand=True)
        self.barra.configure(command=self.lienzo.yview)

        self.interior = kit.marco(self.lienzo, papel)
        self._ventana = self.lienzo.create_window(
            (0, 0), window=self.interior, anchor="nw")

        self.interior.bind("<Configure>", self._cambio_interior)
        self.lienzo.bind("<Configure>", self._cambio_lienzo)
        # El evento de la rueda va a la ventana entera y no al widget
        # bajo el raton, asi que se escucha arriba del todo.
        self.winfo_toplevel().bind_all("<MouseWheel>", self._rueda, add="+")

    def _mover_barra(self, primero: str, ultimo: str) -> None:
        if float(primero) <= 0.0 and float(ultimo) >= 1.0:
            self.barra.pack_forget()
        elif not self.barra.winfo_ismapped():
            self.barra.pack(side="right", fill="y")
        self.barra.set(primero, ultimo)

    def _cambio_interior(self, _evento=None) -> None:
        self.lienzo.configure(scrollregion=self.lienzo.bbox("all"))

    def _cambio_lienzo(self, evento) -> None:
        # El contenido siempre ocupa todo el ancho disponible; lo que
        # sobra o falta es siempre a lo alto.
        self.lienzo.itemconfigure(self._ventana, width=evento.width)

    def _rueda(self, evento) -> None:
        # El registro de actividad tiene su propio desplazamiento. Si el
        # raton esta encima, la rueda es suya: mover la pagina entera
        # mientras se lee el registro seria justo lo contrario de lo que
        # pide quien esta ahi mirando.
        if isinstance(evento.widget, (tk.Text, tk.Listbox)):
            return
        try:
            primero, ultimo = self.lienzo.yview()
        except tk.TclError:
            return
        if primero <= 0.0 and ultimo >= 1.0:
            return  # cabe entero: no hay nada que desplazar
        self.lienzo.yview_scroll(int(-evento.delta / 120), "units")


class Boton(tk.Frame):
    """Boton plano.

    Se hace con un Frame y una Label en vez de con tk.Button porque el
    boton nativo de Windows no deja quitarle el relieve del todo: en
    modo oscuro siempre queda un halo gris alrededor. Con dos widgets
    propios el control del color es total.
    """

    VARIANTES = {
        # variante:      (fondo,        texto,         fondo con el raton)
        "principal": ("tinta", "sobre_tinta", "tinta"),
        "normal": ("panel_alto", "texto", "borde"),
        "sutil": ("panel", "suave", "panel_alto"),
        "peligro": ("panel_alto", "peligro", "borde"),
    }

    def __init__(self, padre, kit: Kit, texto: str, comando=None,
                 variante: str = "normal", rol: str = "boton",
                 alto: int = 0, ancho_min: int = 0, **kw) -> None:
        fondo, tinta, encima = self.VARIANTES[variante]
        super().__init__(padre, bd=0, highlightthickness=0, **kw)

        self.kit = kit
        self.comando = comando
        self.variante = variante
        self._activo = True
        self._papeles = [fondo, tinta, encima]

        relleno_y = alto or tm.ESPACIO["s"]
        self.texto = tk.Label(self, text=texto, font=tm.fuente(rol),
                              cursor="hand2", padx=tm.ESPACIO["m"],
                              pady=relleno_y)
        if ancho_min:
            self.texto.configure(width=ancho_min)
        self.texto.pack(fill="both", expand=True)

        kit.registrar(self, bg=fondo)
        kit.registrar(self.texto, bg=fondo, fg=tinta)

        for widget in (self, self.texto):
            widget.bind("<Enter>", self._entrar)
            widget.bind("<Leave>", self._salir)
            widget.bind("<Button-1>", self._pulsar)

    def _repintar(self, fondo: str, tinta: str) -> None:
        self.configure(bg=self.kit.c(fondo))
        self.texto.configure(bg=self.kit.c(fondo), fg=self.kit.c(tinta))

    def _entrar(self, _evento=None) -> None:
        if self._activo:
            self._repintar(self._papeles[2], self._papeles[1])

    def _salir(self, _evento=None) -> None:
        if self._activo:
            self._repintar(self._papeles[0], self._papeles[1])

    def _pulsar(self, _evento=None) -> None:
        if self._activo and self.comando is not None:
            self.comando()

    # --- api --------------------------------------------------------

    def configurar(self, texto: str | None = None, variante: str | None = None,
                   tono: str | None = None) -> None:
        """Cambia el texto, la variante o solo el color del texto."""
        if texto is not None:
            self.texto.configure(text=texto)
        if variante is not None:
            self.variante = variante
            self._papeles = list(self.VARIANTES[variante])
        if tono is not None:
            self._papeles[1] = tono
        self._salir()

    def habilitar(self, activo: bool) -> None:
        self._activo = activo
        self.texto.configure(cursor="hand2" if activo else "arrow")
        if activo:
            self._salir()
        else:
            self._repintar(self._papeles[0], "apagado")


class Interruptor(tk.Canvas):
    """Conmutador de pastilla, dibujado a mano.

    El Checkbutton de Tk se pinta con el estilo de Windows 95 y no hay
    forma de cambiarlo. Este se dibuja en un lienzo y encaja con el
    resto de la ventana.
    """

    ANCHO, ALTO = 38, 21

    def __init__(self, padre, kit: Kit, variable: tk.BooleanVar,
                 comando=None, fondo: str = "panel") -> None:
        super().__init__(padre, width=self.ANCHO, height=self.ALTO,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.kit = kit
        self.variable = variable
        self.comando = comando
        self._activo = True
        kit.registrar(self, bg=fondo)
        kit.al_cambiar_tema(self.dibujar)

        self.bind("<Button-1>", self._pulsar)
        variable.trace_add("write", lambda *_: self.dibujar())
        self.dibujar()

    def _pulsar(self, _evento=None) -> None:
        if not self._activo:
            return
        self.variable.set(not self.variable.get())
        if self.comando is not None:
            self.comando()

    def habilitar(self, activo: bool) -> None:
        self._activo = activo
        self.configure(cursor="hand2" if activo else "arrow")
        self.dibujar()

    def dibujar(self) -> None:
        self.delete("all")
        encendido = bool(self.variable.get())
        if not self._activo:
            via, bola = "apagado", "panel_alto"
        elif encendido:
            via, bola = "tinta", "sobre_tinta"
        else:
            via, bola = "apagado", "panel"

        pill(self, 0, 0, self.ANCHO, self.ALTO, self.kit.c(via))
        radio = self.ALTO / 2.0 - 3
        centro = self.ANCHO - self.ALTO / 2.0 if encendido else self.ALTO / 2.0
        self.create_oval(centro - radio, self.ALTO / 2.0 - radio,
                         centro + radio, self.ALTO / 2.0 + radio,
                         fill=self.kit.c(bola), outline="")


class Marca(tk.Canvas):
    """El logotipo, dibujado en vez de cargado de un PNG.

    Asi vale para los dos temas sin tener dos ficheros, y sale nitido
    tanto al 100% como al 150% de escalado de Windows.
    """

    def __init__(self, padre, kit: Kit, ancho: int, alto: int,
                 fondo: str = "fondo", tinta: str = "texto") -> None:
        super().__init__(padre, width=ancho, height=alto,
                         highlightthickness=0, bd=0)
        self.kit = kit
        self._tinta = tinta
        self._fondo = fondo
        kit.registrar(self, bg=fondo)
        kit.al_cambiar_tema(self.dibujar)
        self.dibujar()

    def dibujar(self) -> None:
        self.delete("all")
        ancho = int(self["width"])
        alto = int(self["height"])
        for pieza in marca.figuras(ancho, alto):
            papel = self._fondo if pieza.papel == "aire" else self._tinta
            pill(self, pieza.x0, pieza.y0, pieza.x1, pieza.y1, self.kit.c(papel))


class Medidor(tk.Canvas):
    """Medidor de nivel por segmentos, en escala de decibelios.

    Los segmentos se crean una vez y despues solo se les cambia el
    color, y unicamente a los que de verdad cambian: se repinta doce
    veces por segundo y crear y destruir figuras de Tk a ese ritmo era
    lo que mas CPU gastaba de la ventana.

    En una paleta monocroma no hay verde-ambar-rojo que valga, asi que
    el nivel se lee por brillo: los segmentos van de gris a blanco. Los
    ultimos son rojos porque ahi el microfono satura, que es un fallo de
    verdad y no un adorno.
    """

    SEGMENTOS = 32
    UMBRAL_SATURA = 0.88  # a partir de aqui el segmento avisa en rojo
    RANGO_DB = 60.0

    def __init__(self, padre, kit: Kit, alto: int = 10,
                 fondo: str = "panel") -> None:
        super().__init__(padre, height=alto, highlightthickness=0, bd=0)
        self.kit = kit
        self._alto = alto
        self._piezas: list[int] = []
        self._colores: list[str] = []
        self._ancho = 0
        kit.registrar(self, bg=fondo)
        kit.al_cambiar_tema(self.reiniciar)
        self.bind("<Configure>", lambda _e: self.reiniciar())

    def reiniciar(self) -> None:
        self._ancho = 0
        self.pintar(0.0)

    def _color(self, indice: int, encendido: bool) -> str:
        if not encendido:
            return self.kit.c("apagado")
        parte = indice / self.SEGMENTOS
        if parte >= self.UMBRAL_SATURA:
            return self.kit.c("peligro")
        # Degradado de gris a blanco: el nivel se lee por luminosidad.
        return tm.mezclar(self.kit.c("tenue"), self.kit.c("texto"),
                          min(parte / self.UMBRAL_SATURA, 1.0))

    def _rejilla(self, ancho: int) -> None:
        self.delete("all")
        hueco = 2.0
        paso = ancho / self.SEGMENTOS
        self._piezas = [
            self.create_rectangle(i * paso, 0, i * paso + paso - hueco,
                                  self._alto, fill=self.kit.c("apagado"),
                                  outline="")
            for i in range(self.SEGMENTOS)
        ]
        self._colores = [self.kit.c("apagado")] * self.SEGMENTOS
        self._ancho = ancho

    def pintar(self, nivel: float) -> None:
        ancho = self.winfo_width()
        if ancho <= 1:
            return
        if ancho != self._ancho:
            self._rejilla(ancho)

        db = 20.0 * math.log10(max(nivel, 1e-6))
        proporcion = min(max((db + self.RANGO_DB) / self.RANGO_DB, 0.0), 1.0)
        encendidos = int(round(proporcion * self.SEGMENTOS))

        for i in range(self.SEGMENTOS):
            color = self._color(i, i < encendidos)
            if self._colores[i] != color:
                self.itemconfigure(self._piezas[i], fill=color)
                self._colores[i] = color


class Punto(tk.Canvas):
    """El punto de estado de la cabecera: lleno, hueco o apagado."""

    LADO = 10

    def __init__(self, padre, kit: Kit, fondo: str = "fondo") -> None:
        super().__init__(padre, width=self.LADO, height=self.LADO,
                         highlightthickness=0, bd=0)
        self.kit = kit
        self._tono = "tenue"
        self._relleno = True
        kit.registrar(self, bg=fondo)
        kit.al_cambiar_tema(self.dibujar)
        self.dibujar()

    def poner(self, tono: str, relleno: bool = True) -> None:
        if (tono, relleno) == (self._tono, self._relleno):
            return
        self._tono, self._relleno = tono, relleno
        self.dibujar()

    def dibujar(self) -> None:
        self.delete("all")
        color = self.kit.c(self._tono)
        caja = (1, 1, self.LADO - 1, self.LADO - 1)
        if self._relleno:
            self.create_oval(*caja, fill=color, outline="")
        else:
            self.create_oval(*caja, outline=color, width=2)


class BotonTema(tk.Canvas):
    """Sol o luna, dibujados: el simbolo cambia con el tema activo.

    Se dibuja en vez de escribirse con un caracter porque los simbolos
    de sol y luna no estan en todas las tipografias, y cuando faltan
    Windows los sustituye por un recuadro vacio.
    """

    LADO = 30

    def __init__(self, padre, kit: Kit, comando, fondo: str = "fondo") -> None:
        super().__init__(padre, width=self.LADO, height=self.LADO,
                         highlightthickness=0, bd=0, cursor="hand2")
        self.kit = kit
        kit.registrar(self, bg=fondo)
        kit.al_cambiar_tema(self.dibujar)
        self._fondo = fondo
        self.bind("<Button-1>", lambda _e: comando())
        self.bind("<Enter>", lambda _e: self.dibujar("texto"))
        self.bind("<Leave>", lambda _e: self.dibujar())
        self.dibujar()

    def dibujar(self, tono: str = "suave") -> None:
        self.delete("all")
        color = self.kit.c(tono)
        centro = self.LADO / 2.0
        radio = 6.5

        if self.kit.tema == "oscuro":
            # Luna: un circulo al que otro del color del fondo le muerde
            # un trozo. Pintar encima es mas simple que recortar.
            self.create_oval(centro - radio, centro - radio,
                             centro + radio, centro + radio,
                             fill=color, outline="")
            self.create_oval(centro - radio + 4.5, centro - radio - 2.5,
                             centro + radio + 4.5, centro + radio - 2.5,
                             fill=self.kit.c(self._fondo), outline="")
            return

        radio = 4.8
        self.create_oval(centro - radio, centro - radio,
                         centro + radio, centro + radio,
                         fill=color, outline="")
        for i in range(8):
            angulo = i * math.pi / 4.0
            dx, dy = math.cos(angulo), math.sin(angulo)
            self.create_line(centro + dx * (radio + 2.5),
                             centro + dy * (radio + 2.5),
                             centro + dx * (radio + 5.5),
                             centro + dy * (radio + 5.5),
                             fill=color, width=1.6, capstyle="round")


class Tarjeta(tk.Frame):
    """Bloque con borde fino, titulo en mayusculas y cuerpo."""

    def __init__(self, padre, kit: Kit, titulo: str,
                 expandir: bool = False) -> None:
        super().__init__(padre, highlightthickness=1, bd=0)
        kit.registrar(self, bg="panel", highlightbackground="borde",
                      highlightcolor="borde")
        self.kit = kit

        self.cabecera = kit.marco(self, "panel")
        self.cabecera.pack(fill="x", padx=tm.ESPACIO["l"],
                           pady=(tm.ESPACIO["m"] - 1, tm.ESPACIO["s"] - 2))
        kit.etiqueta(self.cabecera, titulo.upper(), "seccion", "tenue",
                     "panel").pack(side="left")

        self.cuerpo = kit.marco(self, "panel")
        self.cuerpo.pack(fill="both", expand=expandir, padx=tm.ESPACIO["l"],
                         pady=(0, tm.ESPACIO["m"]))
        self.cuerpo.columnconfigure(1, weight=1)

    def fila(self, etiqueta: str, indice: int, arriba: int = 2) -> tk.Frame:
        """Una linea "etiqueta a la izquierda, control a la derecha"."""
        self.kit.etiqueta(self.cuerpo, etiqueta, "cuerpo", "suave", "panel",
                          width=11, anchor="w").grid(
            row=indice, column=0, sticky="w", pady=(arriba, 2))
        celda = self.kit.marco(self.cuerpo, "panel")
        celda.grid(row=indice, column=1, sticky="ew", pady=(arriba, 2))
        return celda
