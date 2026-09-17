"""Ventana para editar las listas de palabras desde el programa.

Hasta ahora la unica forma de tocar palabras.txt era abrirlo con el
bloc de notas, lo que obliga a salir del programa, recordar el formato
y volver a pulsar Recargar. Aqui se ven las dos listas enteras, se
busca, se añade, se corrige y se borra, y al guardar se aplica al
censor en marcha sin cortar el audio.

El fichero se sigue pudiendo editar a mano: listas.py guarda respetando
los comentarios y las categorias, asi que los dos caminos conviven.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

import listas
import tema as tm
import widgets as w

ANCHO, ALTO = 720, 700
MARGEN = 24


class Pestana:
    """Una de las dos listas: su fichero, su buscador y su cuadro."""

    def __init__(self, ventana: "VentanaPalabras", clave: str, ruta: str,
                 titulo: str, ayuda: str) -> None:
        self.ventana = ventana
        self.kit = ventana.kit
        self.clave = clave
        self.titulo = titulo
        self.ayuda = ayuda
        self.lista = listas.Lista(ruta)
        # Lo que se ve ahora mismo en el cuadro, que con el buscador
        # puesto es solo una parte. Guarda la linea real de cada fila
        # para poder editar el fichero por su sitio.
        self.visibles: list[listas.Entrada] = []
        self.marco: tk.Frame | None = None

    # --- construccion -----------------------------------------------

    def construir(self, padre: tk.Frame) -> tk.Frame:
        kit = self.kit
        self.marco = kit.marco(padre, "fondo")

        kit.etiqueta(self.marco, self.ayuda, "micro", "tenue", "fondo",
                     anchor="w", justify="left",
                     wraplength=ANCHO - MARGEN * 2).pack(
            fill="x", pady=(0, tm.ESPACIO["m"]))

        # --- alta ---
        alta = kit.marco(self.marco, "fondo")
        alta.pack(fill="x", pady=(0, tm.ESPACIO["s"]))
        self.entrada = self._campo(alta, "Escribe una palabra o una frase…")
        self.entrada.pack(side="left", fill="x", expand=True)
        self.entrada.bind("<Return>", lambda _e: self.anadir())
        w.Boton(alta, kit, "Añadir", self.anadir, "normal", alto=9).pack(
            side="left", padx=(tm.ESPACIO["s"], 0))

        # --- buscador ---
        busca = kit.marco(self.marco, "fondo")
        busca.pack(fill="x", pady=(0, tm.ESPACIO["s"]))
        self.var_busca = tk.StringVar()
        self.buscador = self._campo(busca, "Buscar en la lista…",
                                    variable=self.var_busca)
        self.buscador.pack(side="left", fill="x", expand=True)
        self.var_busca.trace_add("write", lambda *_: self.refrescar())
        w.Boton(busca, kit, "Limpiar", self._limpiar_busqueda, "sutil",
                rol="micro", alto=9).pack(side="left", padx=(tm.ESPACIO["s"], 0))

        # --- cuadro ---
        caja = kit.marco(self.marco, "hundido", highlightthickness=1)
        kit.registrar(caja, highlightbackground="borde", highlightcolor="borde")
        caja.pack(fill="both", expand=True)

        barra = w.BarraAuto(caja)
        self.cuadro = kit.registrar(
            tk.Listbox(caja, font=tm.fuente("cuerpo"), relief="flat", bd=0,
                       highlightthickness=0, activestyle="none",
                       selectmode="extended", yscrollcommand=barra.set),
            bg="hundido", fg="texto", selectbackground="tinta",
            selectforeground="sobre_tinta")
        self.cuadro.pack(fill="both", expand=True, padx=2, pady=2)
        barra.acompanar(self.cuadro)
        self.cuadro.bind("<Double-Button-1>", lambda _e: self.editar())
        self.cuadro.bind("<Delete>", lambda _e: self.quitar())
        self.cuadro.bind("<<ListboxSelect>>", lambda _e: self._pintar_pie())

        # --- pie ---
        pie = kit.marco(self.marco, "fondo")
        pie.pack(fill="x", pady=(tm.ESPACIO["s"], 0))
        self.eti_cuenta = kit.etiqueta(pie, "", "micro", "tenue", "fondo")
        self.eti_cuenta.pack(side="left")
        w.Boton(pie, kit, "Quitar", self.quitar, "peligro", rol="micro",
                alto=8).pack(side="right")
        w.Boton(pie, kit, "Editar", self.editar, "normal", rol="micro",
                alto=8).pack(side="right", padx=(0, tm.ESPACIO["s"]))

        self.refrescar()
        return self.marco

    def _campo(self, padre, pista: str, variable=None) -> tk.Entry:
        """Un cuadro de texto con pista dentro cuando esta vacio.

        Tkinter no tiene "placeholder": se escribe la pista en gris y se
        borra al entrar el cursor.
        """
        campo = self.kit.registrar(
            tk.Entry(padre, font=tm.fuente("cuerpo"), relief="flat", bd=0,
                     highlightthickness=1, textvariable=variable),
            bg="panel_alto", fg="texto", insertbackground="texto",
            highlightbackground="panel_alto", highlightcolor="borde_vivo",
            selectbackground="tinta", selectforeground="sobre_tinta")
        campo.configure(**{"disabledbackground": self.kit.c("panel")})

        def poner_pista() -> None:
            if not campo.get():
                campo.insert(0, pista)
                campo.configure(fg=self.kit.c("tenue"))
                campo._con_pista = True

        def quitar_pista(_evento=None) -> None:
            if getattr(campo, "_con_pista", False):
                campo.delete(0, "end")
                campo.configure(fg=self.kit.c("texto"))
                campo._con_pista = False

        campo._con_pista = False
        campo.bind("<FocusIn>", quitar_pista)
        campo.bind("<FocusOut>", lambda _e: poner_pista())
        poner_pista()
        campo._quitar_pista = quitar_pista
        return campo

    def _texto_campo(self, campo: tk.Entry) -> str:
        return "" if getattr(campo, "_con_pista", False) else campo.get()

    def _limpiar_busqueda(self) -> None:
        self.buscador._con_pista = False
        self.var_busca.set("")
        self.buscador.configure(fg=self.kit.c("texto"))
        self.refrescar()

    # --- pintado ----------------------------------------------------

    def refrescar(self) -> None:
        filtro = listas.normalizar(self._texto_campo(self.buscador))
        todas = self.lista.entradas()
        self.visibles = [e for e in todas if not filtro or filtro in e.texto]

        self.cuadro.delete(0, "end")
        for entrada in self.visibles:
            self.cuadro.insert("end", "  " + entrada.texto)
        self._pintar_pie(len(todas))

    def _pintar_pie(self, total: int | None = None) -> None:
        if total is None:
            total = len(self.lista.entradas())
        sueltas = sum(1 for e in self.lista.entradas() if " " not in e.texto)
        texto = f"{total} términos  ·  {sueltas} palabras, {total - sueltas} frases"
        if len(self.visibles) != total:
            texto = f"{len(self.visibles)} de {texto}"
        seleccion = self.cuadro.curselection()
        if len(seleccion) > 1:
            texto += f"  ·  {len(seleccion)} seleccionados"
        self.eti_cuenta.configure(text=texto)

    # --- acciones ---------------------------------------------------

    def anadir(self) -> None:
        texto = self._texto_campo(self.entrada)
        motivo = listas.valido(texto)
        if motivo:
            messagebox.showwarning("No se puede añadir", motivo,
                                   parent=self.ventana)
            return
        if self.lista.contiene(texto):
            messagebox.showinfo(
                "Ya está en la lista",
                f"“{listas.normalizar(texto)}” ya figura en "
                f"{self.titulo.lower()}.", parent=self.ventana)
            return

        self.lista.anadir(texto)
        self.ventana.marcar_cambios()
        self.entrada.delete(0, "end")
        self._limpiar_busqueda()
        self.refrescar()
        self._ir_a(listas.normalizar(texto))
        self.entrada.focus_set()

    def _ir_a(self, texto: str) -> None:
        """Selecciona un termino y desplaza el cuadro hasta el."""
        for i, entrada in enumerate(self.visibles):
            if entrada.texto == texto:
                self.cuadro.selection_clear(0, "end")
                self.cuadro.selection_set(i)
                self.cuadro.see(i)
                self._pintar_pie()
                return

    def _seleccionadas(self) -> list[listas.Entrada]:
        return [self.visibles[i] for i in self.cuadro.curselection()
                if 0 <= i < len(self.visibles)]

    def editar(self) -> None:
        elegidas = self._seleccionadas()
        if len(elegidas) != 1:
            messagebox.showinfo(
                "Editar", "Elige una sola fila para cambiarla.",
                parent=self.ventana)
            return

        entrada = elegidas[0]
        nuevo = pedir_texto(self.ventana, "Editar término",
                            "Como quieres que quede:", entrada.texto)
        if nuevo is None:
            return

        motivo = listas.valido(nuevo)
        if motivo:
            messagebox.showwarning("No vale", motivo, parent=self.ventana)
            return
        if listas.normalizar(nuevo) == entrada.texto:
            return
        if self.lista.contiene(nuevo, salvo=entrada.linea):
            messagebox.showinfo("Ya está en la lista",
                                "Ese término ya figura en la lista.",
                                parent=self.ventana)
            return

        self.lista.cambiar(entrada.linea, nuevo)
        self.ventana.marcar_cambios()
        self.refrescar()
        self._ir_a(listas.normalizar(nuevo))

    def quitar(self) -> None:
        elegidas = self._seleccionadas()
        if not elegidas:
            messagebox.showinfo("Quitar", "Elige primero que filas quitar.",
                                parent=self.ventana)
            return

        if len(elegidas) == 1:
            pregunta = f"¿Quitar “{elegidas[0].texto}” de la lista?"
        else:
            pregunta = f"¿Quitar {len(elegidas)} términos de la lista?"
        if not messagebox.askyesno("Quitar", pregunta, parent=self.ventana):
            return

        primera = self.cuadro.curselection()[0]
        self.lista.quitar([e.linea for e in elegidas])
        self.ventana.marcar_cambios()
        self.refrescar()

        # Deja seleccionada la fila que ocupa el hueco, para poder
        # seguir borrando sin tener que volver a apuntar con el raton.
        if self.visibles:
            siguiente = min(primera, len(self.visibles) - 1)
            self.cuadro.selection_set(siguiente)
            self.cuadro.see(siguiente)
        self._pintar_pie()


def pedir_texto(padre, titulo: str, pregunta: str, inicial: str = "") -> str | None:
    """Cuadro de dialogo para escribir una linea, con el tema aplicado.

    El simpledialog de Tkinter se pinta con los colores del sistema y
    canta muchisimo al lado del resto de la ventana.
    """
    kit = padre.kit
    dialogo = tk.Toplevel(padre)
    kit.registrar(dialogo, bg="fondo")
    dialogo.title(titulo)
    dialogo.transient(padre)
    dialogo.resizable(False, False)
    respuesta: dict = {"valor": None}

    cuerpo = kit.marco(dialogo, "fondo")
    cuerpo.pack(fill="both", expand=True, padx=MARGEN, pady=MARGEN)
    kit.etiqueta(cuerpo, pregunta, "cuerpo", "suave", "fondo",
                 anchor="w").pack(fill="x", pady=(0, tm.ESPACIO["s"]))

    campo = kit.registrar(
        tk.Entry(cuerpo, font=tm.fuente("cuerpo"), relief="flat", bd=0,
                 highlightthickness=1, width=44),
        bg="panel_alto", fg="texto", insertbackground="texto",
        highlightbackground="panel_alto", highlightcolor="borde_vivo",
        selectbackground="tinta", selectforeground="sobre_tinta")
    campo.pack(fill="x", ipady=6)
    campo.insert(0, inicial)
    campo.select_range(0, "end")

    def aceptar(_evento=None) -> None:
        respuesta["valor"] = campo.get()
        dialogo.destroy()

    botones = kit.marco(cuerpo, "fondo")
    botones.pack(fill="x", pady=(tm.ESPACIO["l"], 0))
    w.Boton(botones, kit, "Guardar", aceptar, "principal", alto=9).pack(
        side="right")
    w.Boton(botones, kit, "Cancelar", dialogo.destroy, "sutil", alto=9).pack(
        side="right", padx=(0, tm.ESPACIO["s"]))

    campo.bind("<Return>", aceptar)
    dialogo.bind("<Escape>", lambda _e: dialogo.destroy())

    dialogo.update_idletasks()
    # Centrada sobre la ventana que la abre, no en una esquina.
    x = padre.winfo_rootx() + (padre.winfo_width() - dialogo.winfo_width()) // 2
    y = padre.winfo_rooty() + (padre.winfo_height() - dialogo.winfo_height()) // 3
    dialogo.geometry(f"+{x}+{y}")

    campo.focus_set()
    dialogo.grab_set()
    padre.wait_window(dialogo)
    return respuesta["valor"]


class VentanaPalabras(tk.Toplevel):
    """Las dos listas, con pestañas."""

    def __init__(self, padre) -> None:
        super().__init__(padre)
        self.padre = padre
        self.kit = padre.kit
        self._hay_cambios = False

        ajustes = padre.config_app
        self.pestanas = [
            Pestana(self, "censuradas", ajustes.ruta_palabras,
                    "Palabras censuradas",
                    "Lo que se tapa con un pitido. No hace falta escribir "
                    "tildes, plurales ni faltas: el detector compara por "
                    "sonido. Un asterisco al final marca una raíz: "
                    "“tont*” cubre tonto, tontos y tontería."),
            Pestana(self, "seguras", ajustes.ruta_seguras,
                    "Palabras seguras",
                    "Lo contrario: palabras normales que suenan parecido a "
                    "una censurada y que NO hay que tapar. Manda sobre la "
                    "otra lista, así que sirve para quitar falsos positivos "
                    "sin bajar la sensibilidad."),
        ]
        self.activa = 0

        self.title("BEEP STREAM  ·  Palabras")
        self.kit.registrar(self, bg="fondo")
        self.geometry(f"{ANCHO}x{ALTO}")
        self.minsize(560, 520)
        self.transient(padre)
        self.protocol("WM_DELETE_WINDOW", self.cerrar)

        self._construir()
        self.kit.adoptar_ventana(self)
        self._cambiar_a(0)

        self.bind("<Escape>", lambda _e: self.cerrar())
        self.bind("<Control-f>", lambda _e: self._ir_al_buscador())
        self.bind("<Control-s>", lambda _e: self.guardar())

    # --- montaje ----------------------------------------------------

    def _construir(self) -> None:
        kit = self.kit

        cabecera = kit.marco(self, "fondo")
        cabecera.pack(fill="x", padx=MARGEN, pady=(MARGEN, tm.ESPACIO["m"]))
        w.Marca(cabecera, kit, 34, 20).pack(side="left", padx=(0, 12))
        kit.etiqueta(cabecera, "Palabras", "titulo", "texto", "fondo").pack(
            side="left")

        # --- pestañas ---
        fila = kit.marco(self, "fondo")
        fila.pack(fill="x", padx=MARGEN)
        self.botones_pestana = []
        for indice, pestana in enumerate(self.pestanas):
            boton = w.Boton(fila, kit, pestana.titulo,
                            lambda i=indice: self._cambiar_a(i), "sutil",
                            alto=9)
            boton.pack(side="left", padx=(0, tm.ESPACIO["s"]))
            self.botones_pestana.append(boton)

        subrayado = kit.marco(self, "borde", height=1)
        subrayado.pack(fill="x", padx=MARGEN, pady=(0, tm.ESPACIO["l"]))

        # --- cuerpo: las dos pestañas montadas, solo se enseña una ---
        self.cuerpo = kit.marco(self, "fondo")
        self.cuerpo.pack(fill="both", expand=True, padx=MARGEN)
        for pestana in self.pestanas:
            pestana.construir(self.cuerpo)

        # --- pie ---
        pie = kit.marco(self, "fondo")
        pie.pack(fill="x", padx=MARGEN, pady=MARGEN)
        self.eti_estado = kit.etiqueta(pie, "", "micro", "tenue", "fondo")
        self.eti_estado.pack(side="left")
        self.boton_guardar = w.Boton(pie, kit, "Guardar y aplicar",
                                     self.guardar, "principal", alto=10)
        self.boton_guardar.pack(side="right")
        w.Boton(pie, kit, "Cerrar", self.cerrar, "sutil", alto=10).pack(
            side="right", padx=(0, tm.ESPACIO["s"]))
        self._pintar_estado()

    def _ir_al_buscador(self) -> str:
        pestana = self.pestanas[self.activa]
        pestana.buscador.focus_set()
        return "break"

    def _cambiar_a(self, indice: int) -> None:
        self.activa = indice
        for i, pestana in enumerate(self.pestanas):
            if i == indice:
                pestana.marco.pack(fill="both", expand=True)
            else:
                pestana.marco.pack_forget()
            self.botones_pestana[i].configurar(
                variante="normal" if i == indice else "sutil",
                tono="texto" if i == indice else "suave")

    # --- estado -----------------------------------------------------

    def marcar_cambios(self) -> None:
        self._hay_cambios = True
        self._pintar_estado()

    def _pintar_estado(self) -> None:
        if self._hay_cambios:
            self.eti_estado.configure(text="Hay cambios sin guardar.",
                                      fg=self.kit.c("texto"))
        else:
            self.eti_estado.configure(text="Todo guardado.",
                                      fg=self.kit.c("tenue"))

    # --- guardar y cerrar -------------------------------------------

    def guardar(self) -> bool:
        vacias = [p.titulo for p in self.pestanas
                  if p.clave == "censuradas" and not p.lista.terminos()]
        if vacias and not messagebox.askyesno(
                "Lista vacía",
                "No queda ninguna palabra censurada. Si guardas así, el "
                "programa no va a tapar nada.\n\n¿Guardar de todas formas?",
                parent=self):
            return False

        try:
            for pestana in self.pestanas:
                pestana.lista.guardar()
        except OSError as error:
            messagebox.showerror(
                "No se puede guardar",
                f"{error}\n\nComprueba que los ficheros no estén abiertos en "
                "otro programa.", parent=self)
            return False

        self._hay_cambios = False
        self._pintar_estado()

        # Se aplica al censor aunque este emitiendo: recargar la lista no
        # corta el audio, solo cambia el detector que consulta el motor.
        try:
            self.padre._recargar_palabras()
        except Exception:  # noqa: BLE001
            pass  # la ventana principal se esta cerrando
        return True

    def cerrar(self) -> None:
        if self._hay_cambios:
            respuesta = messagebox.askyesnocancel(
                "Cambios sin guardar",
                "Has tocado las listas y no lo has guardado.\n\n"
                "¿Guardar antes de cerrar?", parent=self)
            if respuesta is None:
                return
            if respuesta and not self.guardar():
                return
        self.destroy()


def abrir(padre) -> VentanaPalabras:
    ventana = VentanaPalabras(padre)
    ventana.focus_force()
    return ventana
