"""Guia de instalacion y primer arranque.

Se abre sola la primera vez que se ejecuta el programa y despues queda
disponible en el boton "Guia de instalacion" de la ventana.

Montar un censor de directo tiene tres partes que no se adivinan solas:
que hace falta un cable de audio virtual, por que el audio sale con mas
de un segundo de retardo, y que ese mismo retardo hay que repetirlo en
el video o la boca no cuadra con la voz. Un texto largo lo explica mal,
asi que cada paso lleva su diagrama dibujado y, donde se puede, se
comprueba en vivo si la cosa esta bien puesta.

Los diagramas se dibujan sobre lienzos de Tkinter en vez de cargarse
como imagenes: cambian de color con el tema, se ven nitidos con la
pantalla escalada y no hay que mantener dos versiones de cada figura.
"""

from __future__ import annotations

import os
import queue
import webbrowser

import tkinter as tk

import numpy as np
import sounddevice as sd

import dispositivos as disp
import tema as tm
import widgets as w

URL_VBCABLE = "https://vb-audio.com/Cable/"

ANCHO, ALTO = 880, 760
MARGEN = 32
ALTO_LIENZO = 210


# --------------------------------------------------------------------
#  Vocabulario de los diagramas
# --------------------------------------------------------------------

def nodo(lienzo: tk.Canvas, kit: w.Kit, x, y, ancho, alto, titulo,
         subtitulo: str = "", resaltado: bool = False,
         tono_borde: str = "borde") -> None:
    """Una caja con titulo y, si hace falta, una linea pequeña debajo."""
    relleno = kit.c("panel_alto") if resaltado else kit.c("panel")
    w.redondeado(lienzo, x, y, x + ancho, y + alto, 10,
                 fill=relleno, outline=kit.c(tono_borde), width=1)
    centro_x = x + ancho / 2.0
    if subtitulo:
        lienzo.create_text(centro_x, y + alto / 2.0 - 9, text=titulo,
                           font=tm.fuente("fuerte"), fill=kit.c("texto"))
        lienzo.create_text(centro_x, y + alto / 2.0 + 10, text=subtitulo,
                           font=tm.fuente("micro"), fill=kit.c("tenue"))
    else:
        lienzo.create_text(centro_x, y + alto / 2.0, text=titulo,
                           font=tm.fuente("fuerte"), fill=kit.c("texto"))


def flecha(lienzo: tk.Canvas, kit: w.Kit, x0, y, x1, etiqueta: str = "",
           tono: str = "tenue", punteada: bool = False) -> None:
    lienzo.create_line(x0, y, x1, y, fill=kit.c(tono), width=1.5,
                       arrow="last", arrowshape=(9, 11, 4),
                       dash=(3, 3) if punteada else None)
    if etiqueta:
        lienzo.create_text((x0 + x1) / 2.0, y - 12, text=etiqueta,
                           font=tm.fuente("micro"), fill=kit.c(tono))


def rotulo(lienzo: tk.Canvas, kit: w.Kit, x, y, texto: str,
           rol: str = "micro", tono: str = "tenue", anclaje: str = "center",
           ancho_max: int | None = None) -> None:
    lienzo.create_text(x, y, text=texto, font=tm.fuente(rol), fill=kit.c(tono),
                       anchor=anclaje, justify="left",
                       width=ancho_max or 0)


# --------------------------------------------------------------------

class Asistente(tk.Toplevel):

    def __init__(self, padre) -> None:
        super().__init__(padre)
        self.padre = padre
        self.kit = padre.kit
        self.config_app = padre.config_app
        self.paso = 0
        self._escucha: sd.InputStream | None = None
        self._niveles: queue.Queue = queue.Queue(maxsize=8)
        self._repaso: str | None = None

        self.title("BEEP STREAM  ·  Guia de instalacion")
        self.configure(bg=self.kit.c("fondo"))
        self.kit.registrar(self, bg="fondo")
        self.geometry(f"{ANCHO}x{ALTO}")
        self.minsize(ANCHO, 660)
        self.transient(padre)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)

        # El icono no se pone aqui: la ventana principal lo registro con
        # iconbitmap(default=...) y las ventanas hijas lo heredan.
        self.pasos = (
            self._paso_bienvenida,
            self._paso_retardo,
            self._paso_cable,
            self._paso_dispositivos,
            self._paso_obs,
            self._paso_video,
            self._paso_final,
        )

        self._construir()
        self._mostrar()
        self.kit.adoptar_ventana(self)

    # ---------------------------------------------------------------
    #  Armazon
    # ---------------------------------------------------------------

    def _construir(self) -> None:
        cabecera = self.kit.marco(self, "fondo")
        cabecera.pack(fill="x", padx=MARGEN, pady=(MARGEN, tm.ESPACIO["m"]))

        w.Marca(cabecera, self.kit, 36, 21).pack(side="left", padx=(0, 12))
        titulos = self.kit.marco(cabecera, "fondo")
        titulos.pack(side="left")
        self.kit.etiqueta(titulos, "Guia de instalacion", "titulo", "texto",
                          "fondo").pack(anchor="w")
        self.eti_paso = self.kit.etiqueta(cabecera, "", "micro", "tenue", "fondo")
        self.eti_paso.pack(side="right")

        self.progreso = tk.Canvas(self, height=3, highlightthickness=0, bd=0)
        self.kit.registrar(self.progreso, bg="apagado")
        self.progreso.pack(fill="x", padx=MARGEN)
        self.progreso.bind("<Configure>", lambda _e: self._pintar_progreso())

        self.cuerpo = self.kit.marco(self, "fondo")
        self.cuerpo.pack(fill="both", expand=True, padx=MARGEN,
                         pady=tm.ESPACIO["xl"])

        pie = self.kit.marco(self, "fondo")
        pie.pack(fill="x", padx=MARGEN, pady=(0, MARGEN))
        self.boton_atras = w.Boton(pie, self.kit, "Atras", self._atras, "sutil",
                                   alto=11, ancho_min=10)
        self.boton_atras.pack(side="left")
        self.boton_siguiente = w.Boton(pie, self.kit, "Siguiente",
                                       self._siguiente, "principal", alto=11,
                                       ancho_min=14)
        self.boton_siguiente.pack(side="right")
        self.boton_saltar = w.Boton(pie, self.kit, "Saltar guia", self.cerrar,
                                    "sutil", rol="micro", alto=11)
        self.boton_saltar.pack(side="right", padx=(0, tm.ESPACIO["m"]))

    def _pintar_progreso(self) -> None:
        self.progreso.delete("all")
        ancho = self.progreso.winfo_width()
        if ancho <= 1:
            return
        hecho = (self.paso + 1) / len(self.pasos)
        self.progreso.create_rectangle(0, 0, ancho * hecho, 3,
                                       fill=self.kit.c("texto"), outline="")

    def _mostrar(self) -> None:
        self._cerrar_escucha()
        for hijo in self.cuerpo.winfo_children():
            hijo.destroy()

        self.eti_paso.configure(text=f"PASO {self.paso + 1} DE {len(self.pasos)}")
        self._pintar_progreso()
        self.boton_atras.habilitar(self.paso > 0)
        ultimo = self.paso == len(self.pasos) - 1
        self.boton_siguiente.configurar(texto="Terminar" if ultimo else "Siguiente")
        self.boton_saltar.habilitar(not ultimo)

        self.pasos[self.paso]()

    def _siguiente(self) -> None:
        if self.paso == len(self.pasos) - 1:
            self.cerrar()
            return
        self.paso += 1
        self._mostrar()

    def _atras(self) -> None:
        if self.paso > 0:
            self.paso -= 1
            self._mostrar()

    def cerrar(self) -> None:
        self._cerrar_escucha()
        self.config_app["asistente_visto"] = True
        self.config_app.guardar()
        self.destroy()

        # Lo elegido aqui se ha guardado en config.json, pero los
        # desplegables de la ventana principal siguen enseñando lo de
        # antes. Se le pide que vuelva a leerlos, salvo si esta
        # emitiendo: ahi no se tocan los dispositivos.
        motor = getattr(self.padre, "motor", None)
        if motor is None or not motor.en_marcha:
            try:
                self.padre._cargar_dispositivos()
            except Exception:  # noqa: BLE001
                pass  # la ventana principal se esta cerrando

    # ---------------------------------------------------------------
    #  Piezas que usan todos los pasos
    # ---------------------------------------------------------------

    def _titulo(self, texto: str, entradilla: str) -> None:
        self.kit.etiqueta(self.cuerpo, texto, "titulo", "texto", "fondo",
                          anchor="w").pack(fill="x")
        self.kit.etiqueta(self.cuerpo, entradilla, "cuerpo", "suave", "fondo",
                          anchor="w", justify="left",
                          wraplength=ANCHO - MARGEN * 2).pack(
            fill="x", pady=(tm.ESPACIO["s"], tm.ESPACIO["xl"]))

    def _lienzo(self, alto: int = ALTO_LIENZO) -> tk.Canvas:
        lienzo = tk.Canvas(self.cuerpo, height=alto, highlightthickness=0, bd=0)
        self.kit.registrar(lienzo, bg="fondo")
        lienzo.pack(fill="x")
        return lienzo

    def _puntos(self, lineas: list[str], tono: str = "suave") -> None:
        """Una lista con viñetas, alineada por la sangria."""
        caja = self.kit.marco(self.cuerpo, "fondo")
        caja.pack(fill="x", pady=(tm.ESPACIO["xl"], 0))
        for texto in lineas:
            fila = self.kit.marco(caja, "fondo")
            fila.pack(fill="x", pady=3)
            self.kit.etiqueta(fila, "·", "fuerte", "tenue", "fondo").pack(
                side="left", anchor="n", padx=(0, tm.ESPACIO["m"]))
            self.kit.etiqueta(fila, texto, "cuerpo", tono, "fondo", anchor="w",
                              justify="left",
                              wraplength=ANCHO - MARGEN * 2 - 40).pack(
                side="left", fill="x")

    def _aviso(self, texto: str, tono: str = "tenue") -> tk.Label:
        """Una linea destacada dentro de una caja, para lo importante."""
        caja = self.kit.marco(self.cuerpo, "panel", highlightthickness=1)
        self.kit.registrar(caja, highlightbackground="borde",
                           highlightcolor="borde")
        caja.pack(fill="x", pady=(tm.ESPACIO["xl"], 0))
        etiqueta = self.kit.etiqueta(caja, texto, "cuerpo", tono, "panel",
                                     anchor="w", justify="left",
                                     wraplength=ANCHO - MARGEN * 2 - 40)
        etiqueta.pack(fill="x", padx=tm.ESPACIO["l"], pady=tm.ESPACIO["m"])
        return etiqueta

    # ---------------------------------------------------------------
    #  1 · Bienvenida
    # ---------------------------------------------------------------

    def _paso_bienvenida(self) -> None:
        self._titulo(
            "Que hace este programa",
            "Escucha tu microfono, reconoce las palabras que tu decidas y las "
            "tapa con un pitido antes de que salgan al directo. Todo pasa en "
            "tu ordenador: nada se sube a internet.")

        lienzo = self._lienzo()
        lienzo.bind("<Configure>", lambda _e, c=lienzo: self._dibujar_cadena(c))

        self._puntos([
            "Necesitas tres cosas: un microfono, VB-CABLE (gratis, lo "
            "instalamos en el paso 3) y OBS o Streamlabs.",
            "La guia son siete pasos y se tarda unos diez minutos.",
            "Puedes volver a abrirla cuando quieras desde el boton "
            "“Guia de instalacion” de la ventana principal.",
        ])

    def _dibujar_cadena(self, lienzo: tk.Canvas) -> None:
        """Microfono → programa → OBS → plataforma."""
        lienzo.delete("all")
        ancho = lienzo.winfo_width()
        if ancho <= 1:
            return

        kit = self.kit
        y = 62
        alto_caja = 62
        ancho_caja = 132
        hueco = (ancho - ancho_caja * 4) / 3.0
        posiciones = [i * (ancho_caja + hueco) for i in range(4)]

        nodo(lienzo, kit, posiciones[0], y, ancho_caja, alto_caja,
             "Tu microfono", "audio sin filtrar")
        nodo(lienzo, kit, posiciones[1], y, ancho_caja, alto_caja,
             "BEEP STREAM", "detecta y tapa", resaltado=True,
             tono_borde="texto")
        nodo(lienzo, kit, posiciones[2], y, ancho_caja, alto_caja,
             "OBS", "mezcla con el video")
        nodo(lienzo, kit, posiciones[3], y, ancho_caja, alto_caja,
             "Tu directo", "ya censurado")

        for i in range(3):
            flecha(lienzo, kit, posiciones[i] + ancho_caja + 8, y + alto_caja / 2,
                   posiciones[i + 1] - 8,
                   ["voz", "cable virtual", ""][i])

        rotulo(lienzo, kit, posiciones[1] + ancho_caja / 2, y + alto_caja + 26,
               "aqui se pierde algo mas de un segundo\n(es lo que cuesta reconocer)",
               tono="tenue")

    # ---------------------------------------------------------------
    #  2 · El retardo
    # ---------------------------------------------------------------

    def _paso_retardo(self) -> None:
        retardo = int(self.config_app.retardo_ms)
        self._titulo(
            "Por que el audio sale con retardo",
            "Para tapar una palabra hay que reconocerla antes, y reconocerla "
            "lleva tiempo. La solucion es guardar tu voz en un colchon y "
            "emitirla con unas decimas de retraso: cuando el reconocedor "
            "avisa, esa parte todavia no ha salido y se puede tapar.")

        lienzo = self._lienzo(215)
        lienzo.bind("<Configure>",
                    lambda _e, c=lienzo: self._dibujar_retardo(c, retardo))

        self._puntos([
            f"Ahora mismo el colchon es de {retardo} ms. Lo puedes cambiar "
            "en la ventana principal, en CENSURA › Retardo.",
            "Medido con este modelo de voz, el reconocedor tarda hasta 830 ms "
            "en confirmar una palabra. Por debajo de 1250 ms empiezan a "
            "escaparse.",
            "El retardo solo afecta al directo. Tu te sigues oyendo al "
            "instante en los auriculares.",
        ])

        self._aviso(
            "Este retardo hay que repetirlo despues en el video, o tu boca "
            "ira por delante de tu voz. Se explica en el paso 6.")

    # Cuanto dura una palabra corta al hablar. Solo sirve para que las
    # pastillas del diagrama tengan un ancho creible.
    DURACION_PALABRA = 380

    def _dibujar_retardo(self, lienzo: tk.Canvas, retardo: int) -> None:
        """Dos lineas de tiempo sobre un mismo eje.

        Arriba, sin colchon: la palabra ya ha salido cuando el
        reconocedor avisa. Abajo, con colchon: cuando sale, ya se sabia
        que habia que taparla.
        """
        lienzo.delete("all")
        ancho = lienzo.winfo_width()
        if ancho <= 1:
            return

        kit = self.kit
        izquierda, derecha = 118, ancho - 20
        # El eje llega un poco mas alla del instante de emision para que
        # la pastilla tapada quepa entera dentro del dibujo.
        escala = (derecha - izquierda) / (retardo + self.DURACION_PALABRA + 260)

        def x_de(ms: float) -> float:
            return izquierda + ms * escala

        y_sin, y_con, y_eje = 42, 108, 168
        ancho_palabra = self.DURACION_PALABRA * escala

        # Guias verticales de los dos instantes que importan. Van por
        # detras de todo lo demas, que se dibuja despues.
        for ms, tono in ((830, "suave"), (retardo, "texto")):
            lienzo.create_line(x_de(ms), y_sin - 18, x_de(ms), y_eje,
                               fill=kit.c(tono), width=1, dash=(2, 4))

        # --- sin colchon ---
        rotulo(lienzo, kit, izquierda - 14, y_sin, "SIN colchon", "fuerte",
               "tenue", anclaje="e")
        w.pill(lienzo, x_de(0), y_sin - 11, x_de(self.DURACION_PALABRA),
               y_sin + 11, kit.c("tenue"))
        rotulo(lienzo, kit, x_de(0) + ancho_palabra / 2, y_sin, "palabra",
               "micro", "fondo")
        rotulo(lienzo, kit, x_de(830) + 12, y_sin,
               "cuando se detecta, ya se ha emitido", tono="peligro",
               anclaje="w")

        # --- con colchon ---
        rotulo(lienzo, kit, izquierda - 14, y_con, "CON colchon", "fuerte",
               "texto", anclaje="e")
        w.pill(lienzo, x_de(0), y_con - 11, x_de(self.DURACION_PALABRA),
               y_con + 11, kit.c("apagado"))
        rotulo(lienzo, kit, x_de(0) + ancho_palabra / 2, y_con, "palabra",
               "micro", "tenue")
        # La flecha que enseña lo que se espera antes de emitir.
        lienzo.create_line(x_de(self.DURACION_PALABRA) + 4, y_con,
                           x_de(retardo) - 4, y_con, fill=kit.c("apagado"),
                           width=1, dash=(2, 3))
        w.pill(lienzo, x_de(retardo), y_con - 11,
               x_de(retardo + self.DURACION_PALABRA), y_con + 11,
               kit.c("texto"))
        rotulo(lienzo, kit, x_de(retardo) + ancho_palabra / 2, y_con, "tapada",
               "micro", "sobre_tinta")

        # --- eje de tiempo ---
        lienzo.create_line(izquierda, y_eje, derecha, y_eje,
                           fill=kit.c("apagado"), width=1)
        marcas = ((0, "hablas", "tenue"),
                  (830, "830 ms\nse detecta", "suave"),
                  (retardo, f"{retardo} ms\nsale al directo", "texto"))
        for ms, texto, tono in marcas:
            x = x_de(ms)
            lienzo.create_line(x, y_eje, x, y_eje + 5, fill=kit.c(tono), width=1)
            lienzo.create_text(x, y_eje + 10, text=texto, anchor="n",
                               justify="center", font=tm.fuente("micro"),
                               fill=kit.c(tono))

    # ---------------------------------------------------------------
    #  3 · VB-CABLE
    # ---------------------------------------------------------------

    def _paso_cable(self) -> None:
        self._titulo(
            "Instala VB-CABLE",
            "Windows no deja que un programa le pase audio a otro directamente. "
            "VB-CABLE crea un cable de sonido falso: el programa enchufa por un "
            "extremo y OBS escucha por el otro. Es gratuito y se instala una "
            "sola vez.")

        lienzo = self._lienzo(150)
        lienzo.bind("<Configure>", lambda _e, c=lienzo: self._dibujar_cable(c))

        self._puntos([
            "Descarga el paquete, descomprimelo y ejecuta "
            "VBCABLE_Setup_x64.exe con el boton derecho › Ejecutar como "
            "administrador.",
            "Cuando termine, reinicia Windows. Sin reiniciar, los "
            "dispositivos no aparecen del todo.",
            "No hace falta tocar nada mas: no cambies la salida "
            "predeterminada de Windows.",
        ])

        caja = self.kit.marco(self.cuerpo, "panel", highlightthickness=1)
        self.kit.registrar(caja, highlightbackground="borde",
                           highlightcolor="borde")
        caja.pack(fill="x", pady=(tm.ESPACIO["xl"], 0))

        fila = self.kit.marco(caja, "panel")
        fila.pack(fill="x", padx=tm.ESPACIO["l"], pady=tm.ESPACIO["m"])
        self.punto_cable = w.Punto(fila, self.kit, fondo="panel")
        self.punto_cable.pack(side="left", padx=(0, tm.ESPACIO["m"]))
        self.eti_cable = self.kit.etiqueta(fila, "", "fuerte", "texto", "panel")
        self.eti_cable.pack(side="left")

        w.Boton(fila, self.kit, "Comprobar de nuevo", self._comprobar_cable,
                "normal", alto=8).pack(side="right")
        w.Boton(fila, self.kit, "Descargar VB-CABLE",
                lambda: webbrowser.open(URL_VBCABLE), "principal",
                alto=8).pack(side="right", padx=(0, tm.ESPACIO["s"]))

        self._comprobar_cable()

    def _dibujar_cable(self, lienzo: tk.Canvas) -> None:
        lienzo.delete("all")
        ancho = lienzo.winfo_width()
        if ancho <= 1:
            return

        kit = self.kit
        y, alto_caja = 42, 58
        ancho_caja = 158
        hueco = (ancho - ancho_caja * 3) / 2.0
        x = [i * (ancho_caja + hueco) for i in range(3)]

        nodo(lienzo, kit, x[0], y, ancho_caja, alto_caja, "BEEP STREAM",
             "envia tu voz ya censurada")
        nodo(lienzo, kit, x[1], y, ancho_caja, alto_caja, "VB-CABLE",
             "el cable que no existe", resaltado=True, tono_borde="texto")
        nodo(lienzo, kit, x[2], y, ancho_caja, alto_caja, "OBS",
             "recoge el audio")

        flecha(lienzo, kit, x[0] + ancho_caja + 8, y + alto_caja / 2,
               x[1] - 8, "CABLE Input")
        flecha(lienzo, kit, x[1] + ancho_caja + 8, y + alto_caja / 2,
               x[2] - 8, "CABLE Output")

        rotulo(lienzo, kit, ancho / 2.0, y + alto_caja + 28,
               "Input es la entrada del cable y Output su salida: "
               "el programa mete por Input y OBS saca por Output.")

    def _comprobar_cable(self) -> None:
        """Vuelve a mirar si VB-CABLE esta ya instalado."""
        try:
            disp.refrescar()
        except Exception:  # noqa: BLE001
            pass  # con audio abierto puede fallar; se mira lo que haya

        salidas = disp.listar(entrada=False)
        instalado = any("cable input" in n.lower() for _, n in salidas)
        segundo = any("cable-a input" in n.lower() for _, n in salidas)

        if instalado:
            self.punto_cable.poner("texto")
            texto = "VB-CABLE detectado. Puedes seguir."
            if segundo:
                texto += "  (y tambien el segundo cable, CABLE-A)"
            self.eti_cable.configure(text=texto, fg=self.kit.c("texto"))
        else:
            self.punto_cable.poner("peligro")
            self.eti_cable.configure(
                text="Todavia no aparece. Instalalo y reinicia Windows.",
                fg=self.kit.c("peligro"))

    # ---------------------------------------------------------------
    #  4 · Dispositivos
    # ---------------------------------------------------------------

    def _paso_dispositivos(self) -> None:
        self._titulo(
            "Elige el microfono y la salida",
            "La entrada es tu microfono de verdad. La salida tiene que ser "
            "CABLE Input: ahi es donde el programa deja tu voz ya censurada "
            "para que OBS la recoja.")

        self.entradas = disp.listar(entrada=True)
        self.salidas = disp.listar(entrada=False)

        tarjeta = w.Tarjeta(self.cuerpo, self.kit, "Dispositivos")
        tarjeta.pack(fill="x")

        self.combo_entrada = self.kit.combo(tarjeta.fila("Entrada", 0, arriba=0))
        self.combo_entrada["values"] = [f"[{i}] {n}" for i, n in self.entradas]
        self.combo_entrada.pack(fill="x")
        self.combo_entrada.bind("<<ComboboxSelected>>",
                                lambda _: self._abrir_escucha())

        self.combo_salida = self.kit.combo(tarjeta.fila("Salida", 1))
        self.combo_salida["values"] = [f"[{i}] {n}" for i, n in self.salidas]
        self.combo_salida.pack(fill="x")

        self.vu = w.Medidor(tarjeta.fila("Nivel", 2), self.kit)
        self.vu.pack(fill="x", pady=5)

        self.eti_nivel = self.kit.etiqueta(tarjeta.cuerpo, "", "micro", "tenue",
                                           "panel", anchor="w")
        self.eti_nivel.grid(row=3, column=0, columnspan=2, sticky="w",
                            pady=(tm.ESPACIO["s"], 0))

        self._preseleccionar(self.combo_entrada, self.entradas,
                             self.config_app.dispositivo_entrada, None)
        self._preseleccionar(self.combo_salida, self.salidas,
                             self.config_app.dispositivo_salida, "cable input")

        self._puntos([
            "Habla ahora: la barra tiene que moverse y quedarse por la mitad. "
            "Si llega al final en rojo, baja el volumen del microfono en "
            "Windows.",
            "Si la barra no se mueve, el microfono esta silenciado o Windows "
            "no da permiso a las aplicaciones de escritorio.",
            "Lo que elijas aqui se guarda y aparecera ya puesto en la ventana "
            "principal.",
        ])

        self._abrir_escucha()

    def _preseleccionar(self, combo, lista, guardado, preferido) -> None:
        if guardado is not None:
            texto = str(guardado).lower()
            for pos, (indice, nombre) in enumerate(lista):
                if str(indice) == texto or texto in nombre.lower():
                    combo.current(pos)
                    return
        if preferido:
            for pos, (_, nombre) in enumerate(lista):
                if preferido in nombre.lower():
                    combo.current(pos)
                    return
        if lista:
            combo.current(0)

    def _indice(self, combo, lista):
        pos = combo.current()
        return lista[pos][0] if 0 <= pos < len(lista) else None

    def _abrir_escucha(self) -> None:
        """Abre el microfono elegido solo para mover el medidor.

        El nivel se calcula en el hilo de audio y se deja en una cola;
        la ventana lo recoge en su propio repaso, porque a Tkinter no se
        le puede llamar desde el hilo de PortAudio.
        """
        self._cerrar_escucha()
        indice = self._indice(self.combo_entrada, self.entradas)

        def llegada(datos, _cuadros, _tiempo, _estado):
            try:
                self._niveles.put_nowait(float(np.abs(datos).max()))
            except queue.Full:
                pass  # la ventana va justa: se tira el nivel y a otra cosa

        try:
            self._escucha = sd.InputStream(
                device=indice, channels=1, samplerate=48000, blocksize=2048,
                dtype="float32", callback=llegada)
            self._escucha.start()
            self.eti_nivel.configure(text="Escuchando el microfono…",
                                     fg=self.kit.c("tenue"))
        except Exception as error:  # noqa: BLE001
            self._escucha = None
            self.eti_nivel.configure(
                text=f"No se puede abrir: {str(error).splitlines()[0]}",
                fg=self.kit.c("peligro"))
            return

        self._repasar_nivel()

    def _repasar_nivel(self) -> None:
        if self._escucha is None:
            return
        nivel = 0.0
        while True:
            try:
                nivel = max(nivel, self._niveles.get_nowait())
            except queue.Empty:
                break
        self.vu.pintar(nivel)
        self._repaso = self.after(60, self._repasar_nivel)

    def _cerrar_escucha(self) -> None:
        if self._repaso is not None:
            try:
                self.after_cancel(self._repaso)
            except tk.TclError:
                pass
            self._repaso = None
        if self._escucha is not None:
            try:
                self._escucha.stop()
                self._escucha.close()
            except Exception:  # noqa: BLE001
                pass
            self._escucha = None
        # Lo elegido se guarda al salir del paso, no al pulsar Terminar:
        # asi vale aunque se cierre la guia por la mitad.
        self._guardar_dispositivos()

    def _guardar_dispositivos(self) -> None:
        if not hasattr(self, "combo_entrada"):
            return
        try:
            self.config_app["dispositivo_entrada"] = self._indice(
                self.combo_entrada, self.entradas)
            self.config_app["dispositivo_salida"] = self._indice(
                self.combo_salida, self.salidas)
            self.config_app.guardar()
        except tk.TclError:
            pass  # los desplegables ya no existen

    # ---------------------------------------------------------------
    #  5 · OBS
    # ---------------------------------------------------------------

    def _paso_obs(self) -> None:
        self._titulo(
            "Configura OBS o Streamlabs",
            "Solo hay que hacer dos cosas: añadir CABLE Output como fuente de "
            "audio y quitar el microfono crudo. Si dejas los dos, tu voz sale "
            "dos veces y una de ellas sin censurar.")

        lienzo = self._lienzo(190)
        lienzo.bind("<Configure>", lambda _e, c=lienzo: self._dibujar_mezclador(c))

        self._puntos([
            "Ajustes › Audio › Dispositivo de audio auxiliar: elige "
            "CABLE Output (VB-Audio Virtual Cable).",
            "En el mezclador, silencia o quita la fuente de tu microfono "
            "real. Es la que lleva el audio sin filtrar.",
            "Deja la frecuencia de muestreo de OBS en 48 kHz, la misma que "
            "usa el cable: si no coinciden, el audio se va desincronizando.",
            "En la fuente CABLE Output no pongas ningun retardo. El retardo "
            "ya viene aplicado desde aqui.",
        ])

    def _dibujar_mezclador(self, lienzo: tk.Canvas) -> None:
        """El mezclador de OBS tal y como tiene que quedar."""
        lienzo.delete("all")
        ancho = lienzo.winfo_width()
        if ancho <= 1:
            return

        kit = self.kit
        caja_ancho = min(520, ancho - 4)
        x0 = (ancho - caja_ancho) / 2.0
        w.redondeado(lienzo, x0, 8, x0 + caja_ancho, 178, 10,
                     fill=kit.c("panel"), outline=kit.c("borde"), width=1)
        rotulo(lienzo, kit, x0 + 18, 30, "Mezclador de audio", "seccion",
               "tenue", anclaje="w")

        filas = (
            ("CABLE Output  (VB-Audio)", "tu voz ya censurada", True),
            ("Mic/Aux  ·  tu microfono", "quitalo o silencialo", False),
            ("Audio del escritorio", "el sonido del PC, si lo usas", None),
        )
        for i, (nombre, nota, bien) in enumerate(filas):
            y = 62 + i * 38
            tono = {True: "texto", False: "peligro", None: "tenue"}[bien]
            marca_texto = {True: "SI", False: "NO", None: "—"}[bien]

            w.redondeado(lienzo, x0 + 18, y - 13, x0 + 48, y + 13, 6,
                         fill="", outline=kit.c(tono), width=1)
            rotulo(lienzo, kit, x0 + 33, y, marca_texto, "micro", tono)
            rotulo(lienzo, kit, x0 + 60, y, nombre, "cuerpo",
                   "texto" if bien is not False else "suave", anclaje="w")
            rotulo(lienzo, kit, x0 + caja_ancho - 18, y, nota, "micro", tono,
                   anclaje="e")

    # ---------------------------------------------------------------
    #  6 · Sincronizar el video
    # ---------------------------------------------------------------

    def _paso_video(self) -> None:
        retardo = int(self.config_app.retardo_ms)
        self._titulo(
            "Cuadra el video con la voz",
            f"Tu voz sale {retardo} ms mas tarde que tu imagen, asi que en el "
            "directo se veria tu boca moverse antes de oirte. Se arregla "
            "retrasando el video la misma cantidad.")

        lienzo = self._lienzo(200)
        lienzo.bind("<Configure>",
                    lambda _e, c=lienzo: self._dibujar_sincronia(c, retardo))

        self._puntos([
            f"En OBS: boton derecho sobre la camara › Filtros › + › "
            f"Retardo de video (asincrono) › {retardo} ms.",
            f"Haz lo mismo con la captura del juego y con las alertas: todo "
            f"lo que se vea tiene que ir {retardo} ms por detras.",
            "El audio del juego y la musica, si los censuras tambien, ya "
            "salen retrasados por el mismo camino: no les añadas nada.",
            "Lo que NO hay que retrasar es lo que tu oyes por los "
            "auriculares. Eso va directo y sin retardo.",
        ])

        self._aviso(
            f"El retardo de video de OBS gasta memoria de video: guarda "
            f"{retardo} ms de imagen de cada fuente. Si la grafica va justa, "
            "retrasa solo la camara, que es donde se nota el desfase.")

    def _dibujar_sincronia(self, lienzo: tk.Canvas, retardo: int) -> None:
        """Dos barras: el video llega antes; retrasandolo, cuadran."""
        lienzo.delete("all")
        ancho = lienzo.winfo_width()
        if ancho <= 1:
            return

        kit = self.kit
        izquierda = 112
        derecha = ancho - 20
        # Las barras duran lo que el retardo y la fila desplazada ocupa
        # dos: con tres huecos de margen todo entra sin recortes.
        paso = (derecha - izquierda) / 2.7

        for fila, arreglado in enumerate((False, True)):
            y = 46 + fila * 96
            rotulo(lienzo, kit, izquierda - 14, y + 8,
                   "Arreglado" if arreglado else "Sin arreglar", "fuerte",
                   "texto" if arreglado else "tenue", anclaje="e")

            x_video = izquierda + (paso if arreglado else 0)
            w.pill(lienzo, x_video, y - 14, x_video + paso, y + 2,
                   kit.c("suave"))
            rotulo(lienzo, kit, x_video + paso / 2, y - 6, "VIDEO", "micro",
                   "sobre_tinta" if kit.tema == "claro" else "fondo")

            x_voz = izquierda + paso
            w.pill(lienzo, x_voz, y + 14, x_voz + paso, y + 30, kit.c("texto"))
            rotulo(lienzo, kit, x_voz + paso / 2, y + 22, "VOZ", "micro",
                   "sobre_tinta")

            if arreglado:
                lienzo.create_line(x_voz, y - 24, x_voz, y + 40,
                                   fill=kit.c("texto"), width=1, dash=(2, 3))
                rotulo(lienzo, kit, x_voz + paso / 2, y + 46,
                       "los dos llegan a la vez", tono="texto")
            else:
                lienzo.create_line(izquierda, y + 46, x_voz, y + 46,
                                   fill=kit.c("peligro"), width=1,
                                   arrow="both", arrowshape=(6, 7, 3))
                rotulo(lienzo, kit, izquierda + paso / 2, y + 62,
                       f"{retardo} ms de desfase: se te ve antes de oirte",
                       tono="peligro")

    # ---------------------------------------------------------------
    #  7 · Listo
    # ---------------------------------------------------------------

    def _paso_final(self) -> None:
        self._titulo(
            "Ya esta",
            "Todo lo que has configurado queda guardado. Antes de emitir, "
            "conviene hacer una prueba: el modo prueba graba unos segundos y "
            "te deja comparar el antes y el despues sin emitir nada.")

        lienzo = self._lienzo(150)
        lienzo.bind("<Configure>", lambda _e, c=lienzo: self._dibujar_resumen(c))

        self._puntos([
            "Pulsa INICIAR y habla: el nivel se mueve y las detecciones van "
            "saliendo en Actividad.",
            "Edita palabras.txt para poner tus propias palabras, una por "
            "linea, y pulsa Recargar. No hace falta reiniciar.",
            "Si vas justo de CPU, usa Segundo plano: el censor sigue y la "
            "ventana se esconde en la bandeja del reloj.",
        ])

    def _dibujar_resumen(self, lienzo: tk.Canvas) -> None:
        """Estado de las tres cosas que tienen que estar bien."""
        lienzo.delete("all")
        ancho = lienzo.winfo_width()
        if ancho <= 1:
            return

        kit = self.kit
        salidas = disp.listar(entrada=False)
        entradas = disp.listar(entrada=True)
        modelo = os.path.isdir(self.config_app.ruta_modelo)

        comprobaciones = (
            ("VB-CABLE instalado",
             any("cable input" in n.lower() for _, n in salidas)),
            ("Microfono disponible", bool(entradas)),
            ("Modelo de voz cargado", modelo),
        )

        ancho_caja = (ancho - 24) / 3.0
        for i, (texto, bien) in enumerate(comprobaciones):
            x = i * (ancho_caja + 12)
            tono = "texto" if bien else "peligro"
            w.redondeado(lienzo, x, 20, x + ancho_caja, 120, 10,
                         fill=kit.c("panel"), outline=kit.c("borde"), width=1)
            centro = x + ancho_caja / 2.0
            radio = 13
            if bien:
                lienzo.create_oval(centro - radio, 46 - radio, centro + radio,
                                   46 + radio, fill=kit.c("texto"), outline="")
                lienzo.create_line(centro - 6, 46, centro - 2, 51, centro + 6, 40,
                                   fill=kit.c("fondo"), width=2,
                                   capstyle="round", joinstyle="round")
            else:
                lienzo.create_oval(centro - radio, 46 - radio, centro + radio,
                                   46 + radio, outline=kit.c("peligro"), width=2)
                lienzo.create_line(centro - 5, 41, centro + 5, 51,
                                   fill=kit.c("peligro"), width=2, capstyle="round")
                lienzo.create_line(centro + 5, 41, centro - 5, 51,
                                   fill=kit.c("peligro"), width=2, capstyle="round")

            rotulo(lienzo, kit, centro, 88, texto, "cuerpo", tono,
                   ancho_max=int(ancho_caja - 24))


def abrir(padre) -> Asistente:
    """Abre la guia sobre la ventana principal."""
    ventana = Asistente(padre)
    ventana.focus_force()
    return ventana
