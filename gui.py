"""Ventana principal.

Tkinter, que viene con Python y no añade peso al ejecutable. Las piezas
visuales (tarjetas, botones, medidores) estan en widgets.py y los
colores en tema.py; aqui solo queda el montaje y lo que hace cada cosa.

Los avisos del motor llegan desde el hilo de reconocimiento y desde los
callbacks de audio. Tkinter no admite que se le toque desde otro hilo,
asi que todo lo que viene de fuera se encola y se vuelca en el repaso
periodico de la ventana.
"""

from __future__ import annotations

import collections
import gc
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np
import sounddevice as sd

import bandeja
import config as cfg
import dispositivos as disp
import escritorio
import fuentes
import rutas
import tema as tm
import widgets as w
from beeper import guardar_wav
from engine import MotorCensor, procesar_grabacion
from matcher import Detector, leer_lista, leer_seguras

MAX_LINEAS_LOG = 400

# Etiquetas del desplegable de volumen: un 0.22 no le dice nada a nadie.
NOMBRES_VOLUMEN = {
    0.08: "muy suave",
    0.12: "suave",
    0.18: "medio-suave",
    0.22: "medio",
    0.30: "alto",
    0.40: "fuerte",
    0.55: "muy fuerte",
}

DESCRIPCION_ESTILO = {
    "shhh": "ruido de radio: tapa bien y no destaca",
    "suave": "tono grave continuo, sin taladrar",
    "marimba": "nota de madera; en frases largas hace tic-tic",
    "burbuja": "aviso amable de dos notas",
    "aire": "casi mudo: puede parecer un corte de audio",
    "tono": "el pitido de siempre, el mas estridente",
    "archivo": "usa tu beep.wav",
}


def nombre_volumen(valor: float) -> str:
    """Etiqueta del volumen mas cercano al valor guardado."""
    cercano = min(NOMBRES_VOLUMEN, key=lambda v: abs(v - float(valor)))
    return NOMBRES_VOLUMEN[cercano]


def valor_volumen(etiqueta: str) -> float:
    for valor, nombre in NOMBRES_VOLUMEN.items():
        if nombre == etiqueta:
            return valor
    return 0.22


def etiqueta_db(ganancia: float) -> str:
    """Pasa una ganancia (1.0, 0.18...) al decibelio mas cercano.

    En la ventana se enseñan decibelios porque es lo que pone OBS en su
    mezclador, y asi los dos numeros se comparan directamente.
    """
    db = 20.0 * np.log10(max(float(ganancia), 1e-6))
    cercano = min(cfg.DECIBELIOS_PC, key=lambda v: abs(v - db))
    return f"{cercano} dB"


def valor_db(etiqueta: str) -> float:
    """Y al reves: de "-15 dB" a la ganancia que hay que multiplicar."""
    try:
        db = float(etiqueta.replace("dB", "").strip())
    except ValueError:
        return 1.0
    return float(10.0 ** (db / 20.0))


class Aplicacion(tk.Tk):

    ANCHO, ALTO = 700, 900

    def __init__(self) -> None:
        super().__init__()
        # Con la ventana ya creada se puede preguntar a Tk que familias
        # ha encontrado de verdad, que es antes de construir nada: la
        # escala tipografica se resuelve al crear cada widget.
        tm.aplicar_fuentes(*fuentes.elegir(self))

        self.config_app = cfg.cargar()
        self.terminos = leer_lista(self.config_app.ruta_palabras)
        self.seguras = leer_seguras(self.config_app.ruta_seguras)
        self.detector = Detector(self.terminos, self.config_app.modo_deteccion,
                                 self.seguras)
        # El audio del PC lleva su propio detector, normalmente mas
        # agresivo: ahi no habla el usuario sino terceros por voz o por
        # el juego, con mas ruido y peor codec.
        self.detector_pc = self._crear_detector_pc()

        self.motor: MotorCensor | None = None
        # Segundo censor, independiente: el del audio que suena en los
        # auriculares. Va aparte porque puede fallar (o no estar
        # activado) sin tumbar el del microfono, que es el critico.
        self.motor_pc: escritorio.MotorEscritorio | None = None
        self.mensajes: queue.Queue = queue.Queue()
        # Los avisos que aun no se han pintado. En segundo plano la
        # ventana esta escondida y nadie los recoge, asi que se guardan
        # aqui con tope: un directo largo llenaria la cola de miles de
        # lineas que ademas el registro acabaria recortando igual.
        self._pendientes_log: collections.deque = collections.deque(
            maxlen=MAX_LINEAS_LOG)
        self._aviso_sin_senal = False
        # Ultimo contador de muestras visto por motor, para detectar un
        # flujo de audio que se ha parado sin avisar.
        self._ultimo_flujo: dict = {}
        self._bandeja: bandeja.Bandeja | None = None
        self._en_bandeja = False
        # Las etiquetas del repaso periodico se reescribian doce veces
        # por segundo aunque fueran a decir lo mismo. Aqui se guarda lo
        # ultimo que se escribio en cada una para poder saltarse el
        # trabajo cuando el resultado seria identico.
        self._ultimo_texto: dict = {}

        self.tema = str(getattr(self.config_app, "tema", tm.POR_DEFECTO))
        self.kit = w.Kit(self, self.tema)
        self.kit.estilos_ttk()

        self.title("BEEP STREAM")
        self.configure(bg=self.kit.c("fondo"))
        self.kit.registrar(self, bg="fondo")
        self.geometry(f"{self.ANCHO}x{self.ALTO}")
        self.minsize(620, 760)
        self._poner_icono()
        self.protocol("WM_DELETE_WINDOW", self._cerrar)

        self._construir()
        self._cargar_dispositivos()
        self.kit.adoptar_ventana(self)
        self._tick()

        self.after(300, self._quizas_asistente)

    def _poner_icono(self) -> None:
        ruta = rutas.resolver(os.path.join("recursos", "icono.ico"))
        if os.path.exists(ruta):
            try:
                self.iconbitmap(default=ruta)
            except tk.TclError:
                pass

    # ---------------------------------------------------------------
    #  Montaje de la ventana
    # ---------------------------------------------------------------

    def _construir(self) -> None:
        # Cabecera y botones se quedan siempre a la vista; los ajustes,
        # que es lo que crece, van en la zona que se desplaza.
        self._construir_cabecera()
        self._construir_controles()

        self.zona = w.Desplazable(self, self.kit)
        self.zona.pack(fill="both", expand=True)
        self.hoja = self.zona.interior

        audio = w.Tarjeta(self.hoja, self.kit, "Microfono")
        audio.pack(fill="x", padx=tm.ESPACIO["l"], pady=(0, tm.ESPACIO["s"]))
        self.combo_entrada = self.kit.combo(audio.fila("Entrada", 0, arriba=0))
        self.combo_entrada.pack(fill="x")
        self.combo_salida = self.kit.combo(audio.fila("Salida", 1))
        self.combo_salida.pack(fill="x")
        self.vu = w.Medidor(audio.fila("Nivel", 2), self.kit)
        self.vu.pack(fill="x", pady=5)

        self._construir_audio_pc()
        self._construir_censura()
        self._construir_actividad()

        self._refrescar_palabras()
        self._pintar_censor()
        self._pintar_estilo()

    def _construir_cabecera(self) -> None:
        cabecera = self.kit.marco(self, "fondo")
        cabecera.pack(fill="x", padx=tm.ESPACIO["l"],
                      pady=(tm.ESPACIO["l"], tm.ESPACIO["m"]))

        w.Marca(cabecera, self.kit, 44, 26).pack(side="left", padx=(0, 14))

        titulos = self.kit.marco(cabecera, "fondo")
        titulos.pack(side="left")
        self.kit.etiqueta(titulos, "BEEP STREAM", "titulo", "texto",
                          "fondo").pack(anchor="w")
        self.kit.etiqueta(titulos, "Censor de audio para directos", "subtitulo",
                          "tenue", "fondo").pack(anchor="w", pady=(1, 0))

        w.BotonTema(cabecera, self.kit, self._alternar_tema).pack(
            side="right", padx=(tm.ESPACIO["m"], 0))

        estado = self.kit.marco(cabecera, "fondo")
        estado.pack(side="right")
        self.punto = w.Punto(estado, self.kit)
        self.punto.pack(side="left", padx=(0, 7))
        self.eti_estado = self.kit.etiqueta(estado, "PARADO", "estado", "tenue",
                                            "fondo")
        self.eti_estado.pack(side="left")

    def _construir_controles(self) -> None:
        controles = self.kit.marco(self, "fondo")
        controles.pack(fill="x", padx=tm.ESPACIO["l"], pady=(0, tm.ESPACIO["s"]))

        self.boton_marcha = w.Boton(controles, self.kit, "INICIAR",
                                    self._alternar_marcha, "principal",
                                    rol="boton_alto", alto=13)
        self.boton_marcha.pack(side="left", fill="x", expand=True,
                               padx=(0, tm.ESPACIO["s"]))
        self.boton_censor = w.Boton(controles, self.kit, "CENSOR ON",
                                    self._alternar_censor, "normal",
                                    rol="boton_alto", alto=13)
        self.boton_censor.pack(side="left", fill="x", expand=True,
                               padx=(0, tm.ESPACIO["s"]))
        self.boton_mute = w.Boton(controles, self.kit, "MUTE",
                                  self._alternar_mute, "normal",
                                  rol="boton_alto", alto=13)
        self.boton_mute.pack(side="left", fill="x", expand=True)

        extras = self.kit.marco(self, "fondo")
        extras.pack(fill="x", padx=tm.ESPACIO["l"], pady=(0, tm.ESPACIO["m"]))
        for texto, accion, relleno in (
                ("Modo prueba", self._abrir_prueba, (0, tm.ESPACIO["s"])),
                ("Segundo plano", self._activar_rendimiento, (0, tm.ESPACIO["s"])),
                ("Guia de instalacion", self._abrir_asistente, (0, 0))):
            boton = w.Boton(extras, self.kit, texto, accion, "normal", alto=8)
            boton.pack(side="left", fill="x", expand=True, padx=relleno)

    def _construir_audio_pc(self) -> None:
        tarjeta = w.Tarjeta(self.hoja, self.kit, "Audio del PC")
        tarjeta.pack(fill="x", padx=tm.ESPACIO["l"], pady=(0, tm.ESPACIO["s"]))

        self.var_pc = tk.BooleanVar(value=bool(self.config_app.censurar_escritorio))
        self.switch_pc = w.Interruptor(tarjeta.cabecera, self.kit, self.var_pc,
                                       self._cambiar_pc)
        self.switch_pc.pack(side="right")

        self.combo_pc_entrada = self.kit.combo(tarjeta.fila("Escuchar", 0, arriba=0))
        self.combo_pc_entrada.pack(fill="x")
        self.combo_pc_salida = self.kit.combo(tarjeta.fila("Salida", 1))
        self.combo_pc_salida.pack(fill="x")

        celda = tarjeta.fila("Volumen", 2)
        self.var_vol_pc = tk.StringVar(value=etiqueta_db(
            getattr(self.config_app, "volumen_escritorio", 1.0)))
        self.combo_vol_pc = self.kit.combo(
            celda, textvariable=self.var_vol_pc, width=8,
            values=[f"{db} dB" for db in cfg.DECIBELIOS_PC])
        self.combo_vol_pc.pack(side="left")
        self.combo_vol_pc.bind("<<ComboboxSelected>>",
                               lambda _: self._cambiar_volumen_pc())
        self.kit.etiqueta(celda, "respecto a tu voz", "micro", "tenue",
                          "panel").pack(side="left", padx=tm.ESPACIO["m"])

        self.vu_pc = w.Medidor(tarjeta.fila("Nivel", 3), self.kit)
        self.vu_pc.pack(fill="x", pady=5)

        self.eti_pc = self.kit.etiqueta(tarjeta.cuerpo, "", "micro", "tenue",
                                        "panel", anchor="w", justify="left")
        self.eti_pc.grid(row=4, column=0, columnspan=2, sticky="w",
                         pady=(tm.ESPACIO["s"], 0))

    def _construir_censura(self) -> None:
        tarjeta = w.Tarjeta(self.hoja, self.kit, "Censura")
        tarjeta.pack(fill="x", padx=tm.ESPACIO["l"], pady=(0, tm.ESPACIO["s"]))

        celda = tarjeta.fila("Retardo", 0, arriba=0)
        self.var_retardo = tk.StringVar(value=str(self.config_app.retardo_ms))
        self.combo_retardo = self.kit.combo(
            celda, textvariable=self.var_retardo, width=8,
            values=[str(v) for v in cfg.RETARDOS])
        self.combo_retardo.pack(side="left")
        self.kit.etiqueta(celda, "ms  ·  mas alto = mas seguro", "micro",
                          "tenue", "panel").pack(side="left", padx=tm.ESPACIO["m"])

        celda = tarjeta.fila("Sonido", 1)
        self.var_estilo = tk.StringVar(
            value=cfg.NOMBRES_ESTILO.get(
                getattr(self.config_app, "beep_estilo", "shhh"), "shhh (radio)"))
        self.combo_estilo = self.kit.combo(
            celda, textvariable=self.var_estilo, width=16,
            values=list(cfg.NOMBRES_ESTILO.values()))
        self.combo_estilo.pack(side="left")
        self.combo_estilo.bind("<<ComboboxSelected>>", lambda _: self._pintar_estilo())
        w.Boton(celda, self.kit, "Probar", self._probar_beep, "sutil",
                rol="micro", alto=5).pack(side="left", padx=tm.ESPACIO["s"])
        self.eti_estilo = self.kit.etiqueta(celda, "", "micro", "tenue", "panel")
        self.eti_estilo.pack(side="left")

        celda = tarjeta.fila("Beep", 2)
        self.var_beep = tk.StringVar(value=str(self.config_app.beep_ms))
        self.combo_beep = self.kit.combo(
            celda, textvariable=self.var_beep, width=6,
            values=[str(v) for v in cfg.DURACIONES_BEEP])
        self.combo_beep.pack(side="left")
        self.kit.etiqueta(celda, "ms", "micro", "tenue", "panel").pack(
            side="left", padx=(tm.ESPACIO["s"], tm.ESPACIO["m"]))
        self.var_volumen = tk.StringVar(
            value=nombre_volumen(self.config_app.beep_volumen))
        self.combo_volumen = self.kit.combo(
            celda, textvariable=self.var_volumen, width=12,
            values=[nombre_volumen(v) for v in cfg.VOLUMENES_BEEP])
        self.combo_volumen.pack(side="left")

        celda = tarjeta.fila("Palabras", 3)
        self.eti_palabras = self.kit.etiqueta(celda, "", "cuerpo", "texto", "panel")
        self.eti_palabras.pack(side="left")
        w.Boton(celda, self.kit, "Recargar", self._recargar_palabras, "sutil",
                rol="micro", alto=5).pack(side="left", padx=tm.ESPACIO["s"])

    def _construir_actividad(self) -> None:
        """Ultima deteccion y registro comparten tarjeta: las dos cuentan
        lo que esta pasando ahora mismo con el censor."""
        tarjeta = w.Tarjeta(self.hoja, self.kit, "Actividad")
        tarjeta.pack(fill="x", padx=tm.ESPACIO["l"], pady=(0, tm.ESPACIO["l"]))
        w.Boton(tarjeta.cabecera, self.kit, "Limpiar", self._limpiar_log, "sutil",
                rol="micro", alto=3).pack(side="right")

        self.eti_ultima = self.kit.etiqueta(tarjeta.cuerpo, "—", "dato", "tenue",
                                            "panel", anchor="w")
        self.eti_ultima.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.eti_contador = self.kit.etiqueta(tarjeta.cuerpo, "", "micro", "tenue",
                                              "panel", anchor="w")
        self.eti_contador.grid(row=1, column=0, columnspan=2, sticky="ew",
                               pady=(3, tm.ESPACIO["m"]))

        caja = self.kit.marco(tarjeta.cuerpo, "hundido", highlightthickness=1)
        self.kit.registrar(caja, highlightbackground="borde", highlightcolor="borde")
        caja.grid(row=2, column=0, columnspan=2, sticky="nsew")

        barra = ttk.Scrollbar(caja, style="BS.Vertical.TScrollbar")
        barra.pack(side="right", fill="y")
        self.log = self.kit.registrar(
            tk.Text(caja, font=tm.fuente("mono"), relief="flat", height=9,
                    wrap="word", bd=0, padx=tm.ESPACIO["m"], pady=tm.ESPACIO["s"],
                    highlightthickness=0, yscrollcommand=barra.set,
                    spacing1=1, spacing3=1),
            bg="hundido", fg="suave", insertbackground="texto",
            selectbackground="panel_alto", selectforeground="texto")
        self.log.pack(fill="both", expand=True)
        barra.configure(command=self.log.yview)
        self._marcas_log()
        self.log.configure(state="disabled")
        self.kit.al_cambiar_tema(self._marcas_log)

    def _marcas_log(self) -> None:
        """Colores de las lineas del registro.

        Solo hay tres niveles y dos colores: lo que va mal se lee en
        rojo y todo lo demas en gris, mas o menos apagado segun importe.
        """
        self.log.tag_config("info", foreground=self.kit.c("tenue"))
        self.log.tag_config("ok", foreground=self.kit.c("suave"))
        self.log.tag_config("censura", foreground=self.kit.c("texto"))
        self.log.tag_config("error", foreground=self.kit.c("peligro"))

    # ---------------------------------------------------------------
    #  Tema
    # ---------------------------------------------------------------

    def _alternar_tema(self) -> None:
        self.tema = tm.contrario(self.tema)
        self.config_app["tema"] = self.tema
        self.config_app.guardar()
        self.kit.cambiar_tema(self.tema)
        # La paleta es otra: lo que se escribio antes ya no vale como
        # referencia y hay que dejar que se repinte todo una vez.
        self._ultimo_texto.clear()
        self._pintar_marcha()
        self._pintar_mute()
        self._pintar_censor()
        self._pintar_aviso_pc()

    # ---------------------------------------------------------------
    #  Dispositivos
    # ---------------------------------------------------------------

    def _cargar_dispositivos(self) -> None:
        # La lista viene ordenada por API: primero WASAPI, que es la mas
        # fiable en Windows, y sin WDM-KS, que es exclusiva y choca con
        # OBS. El nombre lleva la API detras para poder distinguir las
        # tres copias del mismo aparato.
        self.entradas = disp.listar(entrada=True)
        self.salidas = disp.listar(entrada=False)

        self.combo_entrada["values"] = [f"[{i}] {n}" for i, n in self.entradas]
        self.combo_salida["values"] = [f"[{i}] {n}" for i, n in self.salidas]

        try:
            defecto_entrada, defecto_salida = sd.default.device
        except (TypeError, ValueError):
            defecto_entrada = defecto_salida = None

        # El predeterminado de Windows suele venir por DirectSound; se
        # cambia por la copia del mismo aparato en la API mas fiable.
        self._preseleccionar(self.combo_entrada, self.entradas,
                             self.config_app.dispositivo_entrada, None,
                             disp.mejor_api(defecto_entrada, entrada=True))
        self._preseleccionar(self.combo_salida, self.salidas,
                             self.config_app.dispositivo_salida, "cable input",
                             disp.mejor_api(defecto_salida, entrada=False))

        if not self.hay_cable():
            self._registrar(
                "VB-CABLE no detectado. Sin el, el audio censurado no llega a "
                "OBS. Abre la guia de instalacion para ponerlo.", "error")

        self._cargar_dispositivos_pc()

    def hay_cable(self) -> bool:
        """Si VB-CABLE esta instalado. Lo consulta tambien el asistente."""
        return any("cable input" in n.lower() for _, n in self.salidas)

    def _cargar_dispositivos_pc(self) -> None:
        """Llena los desplegables del audio del PC.

        Lo que se escucha son SALIDAS de Windows, no entradas: se pide
        una copia de lo que ya suena por ellas. Y como los indices de
        PyAudio no son los de sounddevice, aqui se trabaja con nombres.
        """
        if not escritorio.DISPONIBLE:
            self.var_pc.set(False)
            self.switch_pc.habilitar(False)
            for combo in (self.combo_pc_entrada, self.combo_pc_salida,
                          self.combo_vol_pc):
                combo.configure(state="disabled")
            self._pintar_aviso_pc()
            return

        self.salidas_pc = escritorio.salidas_capturables()
        self.combo_pc_entrada["values"] = [n for _, n in self.salidas_pc]
        self.combo_pc_salida["values"] = [f"[{i}] {n}" for i, n in self.salidas]

        guardado = self.config_app.dispositivo_escritorio
        elegido = 0
        for pos, (clave, _) in enumerate(self.salidas_pc):
            if guardado and str(guardado).lower() in clave.lower():
                elegido = pos
                break
        else:
            # Sin nada guardado, la salida predeterminada de Windows es
            # lo que se quiere el 99% de las veces: los auriculares.
            try:
                _, defecto = sd.default.device
                nombre = sd.query_devices(defecto)["name"].strip().lower()
                for pos, (clave, _) in enumerate(self.salidas_pc):
                    if clave.strip().lower()[:20] in nombre:
                        elegido = pos
                        break
            except Exception:  # noqa: BLE001
                pass
        if self.salidas_pc:
            self.combo_pc_entrada.current(elegido)

        # Para la salida se busca el segundo cable; si no esta instalado
        # se cae al primero, que tambien vale: Windows mezcla los dos
        # flujos y salen por el cable como una sola fuente.
        self._preseleccionar(self.combo_pc_salida, self.salidas,
                             self.config_app.dispositivo_salida_escritorio,
                             "cable-a input", None)
        if not any("cable-a input" in n.lower() for _, n in self.salidas):
            self._preseleccionar(self.combo_pc_salida, self.salidas, None,
                                 "cable input", None)

        # El aviso depende de que cables haya elegidos, asi que se
        # reescribe en cuanto se toca cualquiera de los dos.
        for combo in (self.combo_pc_salida, self.combo_salida):
            combo.bind("<<ComboboxSelected>>", lambda _: self._pintar_aviso_pc())

        self._pintar_aviso_pc()

    def _pintar_aviso_pc(self) -> None:
        """Explica en una linea que va a pasar con lo que hay elegido."""
        if not escritorio.DISPONIBLE:
            # Se reescribe aqui y no solo al arrancar porque al cambiar
            # de tema el kit repinta la etiqueta con su color registrado
            # y se perderia el rojo.
            self.eti_pc.configure(text="No disponible: " + escritorio.MOTIVO + ".",
                                  fg=self.kit.c("peligro"))
            return

        salida_pc = self._indice(self.combo_pc_salida, self.salidas)
        salida_micro = self._indice(self.combo_salida, self.salidas)

        if not self.var_pc.get():
            texto = "Apagado: por el cable solo va tu microfono censurado."
        elif salida_pc == salida_micro:
            texto = "Micro y PC censurados salen juntos por el mismo cable."
        else:
            texto = "Micro y PC censurados salen por cables separados."
        self.eti_pc.configure(text=texto, fg=self.kit.c("tenue"))

    def _cambiar_volumen_pc(self) -> None:
        """El volumen del audio del PC si se puede tocar en directo.

        No reabre ningun flujo: es una multiplicacion en el ultimo paso,
        asi que sirve para cuadrar el juego con la voz sobre la marcha.
        """
        ganancia = valor_db(self.var_vol_pc.get())
        self.config_app["volumen_escritorio"] = ganancia
        self.config_app.guardar()
        if self.motor_pc is not None:
            self.motor_pc.ganancia = ganancia

    def _cambiar_pc(self) -> None:
        """Enciende o apaga el canal del PC sin parar el del microfono."""
        self.config_app["censurar_escritorio"] = bool(self.var_pc.get())
        self.config_app.guardar()
        self._pintar_aviso_pc()

        if self.motor is None or not self.motor.en_marcha:
            return  # se aplicara al darle a INICIAR

        if self.var_pc.get():
            self._iniciar_pc()
        else:
            self._parar_pc()

    def _pintar_estilo(self) -> None:
        self.eti_estilo.configure(
            text=DESCRIPCION_ESTILO.get(self._estilo_elegido(), ""))

    def _estilo_elegido(self) -> str:
        etiqueta = self.var_estilo.get()
        for clave, nombre in cfg.NOMBRES_ESTILO.items():
            if nombre == etiqueta:
                return clave
        return "tono"

    def _preseleccionar(self, combo, lista, guardado, preferido, defecto) -> None:
        """Elige dispositivo: lo guardado, luego el preferido por nombre
        (VB-CABLE), luego el predeterminado de Windows, y si nada de eso
        existe, el primero de la lista."""
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
        if defecto is not None:
            for pos, (indice, _) in enumerate(lista):
                if indice == defecto:
                    combo.current(pos)
                    return
        if lista:
            combo.current(0)

    def _indice(self, combo, lista):
        pos = combo.current()
        return lista[pos][0] if 0 <= pos < len(lista) else None

    # ---------------------------------------------------------------
    #  Registro
    # ---------------------------------------------------------------

    def _registrar(self, mensaje: str, nivel: str = "info") -> None:
        self.mensajes.put((mensaje, nivel))

    def _volcar_mensajes(self) -> None:
        """Pasa lo que hayan dicho los motores al registro de la ventana.

        La cola se vacia siempre, incluso escondida en la bandeja: es un
        buzon entre hilos y dejarlo sin recoger durante horas solo sirve
        para acumular memoria. Lo que no se hace escondido es pintar,
        que es lo caro.
        """
        while True:
            try:
                self._pendientes_log.append(self.mensajes.get_nowait())
            except queue.Empty:
                break

        if self._en_bandeja or not self._pendientes_log:
            return

        pendientes = list(self._pendientes_log)
        self._pendientes_log.clear()

        self.log.configure(state="normal")
        for mensaje, nivel in pendientes:
            self.log.insert("end", time.strftime("%H:%M:%S  ") + mensaje + "\n",
                            nivel)

        sobrantes = int(self.log.index("end-1c").split(".")[0]) - MAX_LINEAS_LOG
        if sobrantes > 0:
            self.log.delete("1.0", f"{sobrantes}.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _limpiar_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ---------------------------------------------------------------
    #  Palabras
    # ---------------------------------------------------------------

    def _refrescar_palabras(self) -> None:
        sueltas = sum(1 for t in self.terminos if " " not in t)
        self.eti_palabras.config(
            text=f"{len(self.terminos)}  ·  {sueltas} palabras, "
                 f"{len(self.terminos) - sueltas} frases")

    def _crear_detector_pc(self) -> Detector:
        modo = str(getattr(self.config_app, "modo_deteccion_escritorio",
                           self.config_app.modo_deteccion))
        return Detector(self.terminos, modo, self.seguras)

    def _recargar_palabras(self) -> None:
        try:
            self.terminos = leer_lista(self.config_app.ruta_palabras)
        except OSError as error:
            messagebox.showerror("palabras.txt", f"No se puede leer:\n{error}")
            return

        self.seguras = leer_seguras(self.config_app.ruta_seguras)
        self.detector = Detector(self.terminos, self.config_app.modo_deteccion,
                                 self.seguras)
        self.detector_pc = self._crear_detector_pc()
        if self.motor is not None:
            self.motor.detector = self.detector  # se aplica sin cortar el audio
        if self.motor_pc is not None:
            self.motor_pc.detector = self.detector_pc
        self._refrescar_palabras()
        self._registrar(f"Lista recargada: {len(self.terminos)} terminos.", "ok")

    # ---------------------------------------------------------------
    #  Marcha y parada
    # ---------------------------------------------------------------

    def _guardar_ajustes(self) -> None:
        self.config_app["dispositivo_entrada"] = self._indice(
            self.combo_entrada, self.entradas)
        self.config_app["dispositivo_salida"] = self._indice(
            self.combo_salida, self.salidas)
        self.config_app["retardo_ms"] = int(self.var_retardo.get())
        self.config_app["beep_ms"] = int(self.var_beep.get())
        self.config_app["beep_volumen"] = valor_volumen(self.var_volumen.get())
        self.config_app["beep_estilo"] = self._estilo_elegido()

        if escritorio.DISPONIBLE:
            self.config_app["censurar_escritorio"] = bool(self.var_pc.get())
            # La salida a escuchar se guarda por NOMBRE: los indices de
            # PyAudio bailan segun lo que haya conectado.
            pos = self.combo_pc_entrada.current()
            if 0 <= pos < len(self.salidas_pc):
                self.config_app["dispositivo_escritorio"] = self.salidas_pc[pos][0]
            self.config_app["dispositivo_salida_escritorio"] = self._indice(
                self.combo_pc_salida, self.salidas)
            self.config_app["volumen_escritorio"] = valor_db(self.var_vol_pc.get())

        self.config_app.guardar()

    def _alternar_marcha(self) -> None:
        if self.motor is not None and self.motor.en_marcha:
            self._parar()
        else:
            self._iniciar()

    def _iniciar(self) -> None:
        self._guardar_ajustes()

        if int(self.var_retardo.get()) < cfg.RETARDO_MINIMO_SEGURO:
            seguir = messagebox.askyesno(
                "Retardo corto",
                f"Has elegido {self.var_retardo.get()} ms.\n\n"
                f"Medido con este modelo, el reconocimiento tarda hasta "
                f"830 ms en confirmar una palabra. Por debajo de "
                f"{cfg.RETARDO_MINIMO_SEGURO} ms se pueden escapar "
                f"palabras al directo.\n\n¿Continuar de todas formas?")
            if not seguir:
                return

        salida = self._indice(self.combo_salida, self.salidas)
        nombre_salida = next((n for i, n in self.salidas if i == salida), "")
        if "cable input" not in nombre_salida.lower():
            seguir = messagebox.askyesno(
                "La salida no es VB-CABLE",
                f"Has elegido:\n\n{nombre_salida}\n\n"
                "Para que OBS reciba el audio censurado la salida "
                "deberia ser 'CABLE Input'.\n\n¿Continuar de todas formas?")
            if not seguir:
                return

        try:
            self.motor = MotorCensor(self.config_app, self.detector, self._registrar)
            self.motor.iniciar()
        except Exception as error:  # noqa: BLE001
            self.motor = None
            messagebox.showerror("No se puede iniciar", str(error))
            self._registrar(f"Error al iniciar: {error}", "error")
            return

        self._bloquear_ajustes(True)

        if self.var_pc.get():
            self._iniciar_pc()

        self._aviso_sin_senal = False
        self._pintar_marcha()

    def _iniciar_pc(self) -> None:
        """Arranca el censor del audio del PC.

        Si falla no se para nada: el microfono, que es lo que puede
        costar una sancion, sigue censurandose igual. Solo se apaga el
        interruptor y se explica el motivo.
        """
        if self.motor_pc is not None and self.motor_pc.en_marcha:
            return
        try:
            self.motor_pc = escritorio.MotorEscritorio(
                self.config_app, self.detector_pc, self._registrar)
            self.motor_pc.censor_activo = self.config_app.censor_activo
            self.motor_pc.iniciar()
        except Exception as error:  # noqa: BLE001
            self.motor_pc = None
            self.var_pc.set(False)
            self._pintar_aviso_pc()
            self._registrar(f"Audio del PC: {error}", "error")
            messagebox.showerror(
                "No se puede censurar el audio del PC",
                f"{error}\n\nEl microfono sigue censurandose con normalidad.")

    def _parar_pc(self) -> None:
        if self.motor_pc is not None:
            self.motor_pc.parar()
            self.motor_pc = None
        self.vu_pc.pintar(0.0)

    def _bloquear_ajustes(self, bloquear: bool) -> None:
        """En marcha no se tocan dispositivos ni retardos.

        Cambiarlos con el audio corriendo obligaria a reabrir los flujos
        a media emision, que es justo cuando no se puede fallar.
        """
        estado = "disabled" if bloquear else "readonly"
        for combo in (self.combo_entrada, self.combo_salida, self.combo_retardo,
                      self.combo_beep, self.combo_volumen, self.combo_estilo,
                      self.combo_pc_entrada, self.combo_pc_salida):
            combo.configure(state=estado)
        # El volumen del PC se queda libre: es una multiplicacion al
        # vuelo, no hay que reabrir nada para cambiarlo.
        if not escritorio.DISPONIBLE:
            for combo in (self.combo_pc_entrada, self.combo_pc_salida):
                combo.configure(state="disabled")

    def _parar(self) -> None:
        if self.motor is not None:
            self.motor.parar()
            self.motor = None
        self._parar_pc()

        self._bloquear_ajustes(False)
        self._pintar_marcha()
        self.vu.pintar(0.0)

    # ---------------------------------------------------------------
    #  Censor y silencio
    # ---------------------------------------------------------------

    def _alternar_censor(self) -> None:
        self.config_app["censor_activo"] = not self.config_app.censor_activo
        self.config_app.guardar()
        # Los dos canales van a la par: si se apaga el censor, se apaga
        # entero. Tener uno filtrando y el otro no seria la trampa
        # perfecta para colar una palabrota creyendose a salvo.
        for motor in (self.motor, self.motor_pc):
            if motor is not None:
                motor.censor_activo = self.config_app.censor_activo
        self._pintar_censor()
        self._registrar(
            "Censor ACTIVADO." if self.config_app.censor_activo
            else "Censor DESACTIVADO: el audio pasa sin filtrar.",
            "ok" if self.config_app.censor_activo else "error")

    def _alternar_mute(self) -> None:
        if self.motor is None:
            return
        self.motor.silenciado = not self.motor.silenciado
        activo = self.motor.silenciado
        self._pintar_mute()
        self._registrar("Microfono silenciado." if activo else "Microfono abierto.",
                        "error" if activo else "ok")

    def _pintar_marcha(self) -> None:
        en_marcha = self.motor is not None and self.motor.en_marcha
        self.boton_marcha.configurar(
            texto="PARAR" if en_marcha else "INICIAR",
            variante="normal" if en_marcha else "principal")

    def _pintar_mute(self) -> None:
        mudo = self.motor is not None and self.motor.silenciado
        self.boton_mute.configurar(texto="SILENCIADO" if mudo else "MUTE",
                                   variante="peligro" if mudo else "normal")

    def _pintar_censor(self) -> None:
        activo = self.config_app.censor_activo
        self.boton_censor.configurar(
            texto="CENSOR ON" if activo else "CENSOR OFF",
            variante="normal" if activo else "peligro")

    def _escribir_eti(self, widget, texto: str, tono: str | None = None) -> None:
        """Cambia una etiqueta solo si de verdad va a decir otra cosa.

        Tkinter no compara: cada .config(text=...) marca el widget sucio
        y lo vuelve a dibujar, cueste lo que cueste. El repaso pasa por
        aqui doce veces por segundo y casi siempre con el mismo texto.
        """
        nuevo = (texto, tono)
        if self._ultimo_texto.get(widget) == nuevo:
            return
        self._ultimo_texto[widget] = nuevo
        if tono is None:
            widget.config(text=texto)
        else:
            widget.config(text=texto, fg=self.kit.c(tono))

    # ---------------------------------------------------------------
    #  Repaso periodico
    # ---------------------------------------------------------------

    def _tick(self) -> None:
        self._atender_bandeja()

        if self._en_bandeja:
            # Escondida: no se dibuja nada. Solo se vigila el motor, se
            # recogen los avisos (sin pintarlos) y se actualiza el globo
            # del icono, que ademas solo llama a Windows si de verdad ha
            # cambiado algo.
            if self.motor is not None and self.motor.en_marcha:
                self._vigilar_senal()
            self._volcar_mensajes()
            self._refrescar_bandeja()
            self.after(1000, self._tick)
            return

        self._volcar_mensajes()

        caido = self._motor_caido()
        if caido:
            self._escribir_eti(self.eti_estado, "FALLO", "peligro")
            self.punto.poner("peligro")
            self._escribir_eti(self.eti_ultima, caido, "peligro")

        if self.motor is not None and self.motor.en_marcha:
            stats = self.motor.stats

            if caido:
                pass  # ya lo dice la cabecera, y en rojo
            elif self.motor.silenciado:
                self._escribir_eti(self.eti_estado, "SILENCIADO", "peligro")
                self.punto.poner("peligro")
            elif not self.motor.censor_activo:
                self._escribir_eti(self.eti_estado, "SIN CENSURA", "peligro")
                self.punto.poner("peligro", relleno=False)
            else:
                self._escribir_eti(self.eti_estado, "ACTIVO", "texto")
                self.punto.poner("texto")

            if stats.ultima and not caido:
                self._escribir_eti(self.eti_ultima,
                                   f"“{stats.ultima}”  ·  CENSURADO",
                                   "texto")

            partes = [f"{stats.censuras} censuras",
                      f"retardo real {self.motor.retardo_real_ms:.0f} ms"]
            if stats.margen_minimo_ms != float("inf"):
                partes.append(f"margen minimo {stats.margen_minimo_ms:.0f} ms")
            if stats.tardias:
                partes.append(f"{stats.tardias} TARDIAS")
            if stats.cortes_entrada or stats.cortes_salida:
                partes.append(f"cortes {stats.cortes_entrada}/{stats.cortes_salida}")
            if self.motor_pc is not None and self.motor_pc.en_marcha:
                partes.append(f"PC: {self.motor_pc.stats.censuras} censuras")
            self._escribir_eti(self.eti_contador, "   ·   ".join(partes))

            self.vu.pintar(self.motor.nivel)
            self._vigilar_senal()
        elif not caido:
            self._escribir_eti(self.eti_estado, "PARADO", "tenue")
            self.punto.poner("apagado")

        if self.motor_pc is not None and self.motor_pc.en_marcha:
            self.vu_pc.pintar(self.motor_pc.nivel)

        self.after(80, self._tick)

    def _motor_caido(self) -> str:
        """Texto del fallo si algun censor se ha muerto por el camino.

        El audio sigue saliendo al directo aunque el reconocimiento se
        caiga, asi que este es el aviso mas importante de la ventana: no
        estas parado, estas emitiendo sin filtrar.
        """
        if self.motor is not None and self.motor.fallo:
            return "El censor del MICROFONO se ha caido: emite SIN CENSURAR"
        if self.motor_pc is not None and self.motor_pc.fallo:
            return "El censor del AUDIO DEL PC se ha caido: emite SIN CENSURAR"
        return self._flujo_parado()

    def _flujo_parado(self) -> str:
        """Avisa si un motor ha dejado de recibir audio sin darse cuenta.

        Los dos canales se vigilan distinto a proposito. El microfono
        siempre entrega muestras, aunque sean silencio, asi que un
        contador parado solo puede significar que el flujo se murio. El
        loopback del PC, en cambio, no entrega nada mientras no suene
        nada: ahi el contador no dice nada y hay que preguntarle al
        flujo si sigue abierto.
        """
        if self.motor is not None and self.motor.en_marcha:
            ahora = time.time()
            escritas = self.motor.linea.escritas
            visto, cuando = self._ultimo_flujo.get("micro", (None, ahora))
            if escritas != visto:
                self._ultimo_flujo["micro"] = (escritas, ahora)
            elif ahora - cuando > 4.0:
                return "El MICROFONO ha dejado de entrar audio (flujo parado)"
        else:
            self._ultimo_flujo.pop("micro", None)

        if (self.motor_pc is not None and self.motor_pc.en_marcha
                and not self.motor_pc.entrada_viva):
            return "El AUDIO DEL PC ha perdido la captura"
        return ""

    def _vigilar_senal(self) -> None:
        """Avisa si el microfono lleva un rato abierto y mudo.

        Un microfono silenciado abre sin dar ningun error y el censor
        parece funcionar: la unica pista es que el nivel no se mueve. En
        directo eso significa emitir sin sonido.
        """
        if self._aviso_sin_senal or self.motor is None:
            return
        if time.time() - self.motor.arrancado_en < 6.0:
            return

        self._aviso_sin_senal = True
        if self.motor.nivel_maximo < 0.0005:
            self._registrar(
                "El microfono no da senal (silencio absoluto en 6 s). "
                "Comprueba que no este silenciado: en los auriculares con "
                "brazo, subirlo lo silencia. Mira tambien el Panel de "
                "control de Sonido y los permisos de Windows.", "error")

    # ---------------------------------------------------------------
    #  Segundo plano: a la bandeja del sistema
    # ---------------------------------------------------------------

    def _activar_rendimiento(self) -> None:
        """Esconde la ventana y deja el censor corriendo en la bandeja.

        No toca el reconocimiento: lo que se apaga es el dibujado de la
        interfaz, que es lo unico que se puede quitar sin arriesgar que
        se escape una palabra.
        """
        if self._bandeja is None:
            self._bandeja = bandeja.Bandeja(
                "BEEP STREAM",
                [
                    ("Mostrar ventana", "mostrar"),
                    ("", None),
                    ("Censor ON / OFF", "censor"),
                    ("Silenciar / abrir microfono", "mute"),
                    ("", None),
                    ("Salir", "salir"),
                ],
                al_doble_clic="mostrar",
            )
            if not self._bandeja.mostrar():
                motivo = self._bandeja.error or "motivo desconocido"
                self._bandeja = None
                self._registrar(
                    f"No se pudo crear el icono de bandeja: {motivo}", "error")
                messagebox.showerror(
                    "Bandeja del sistema",
                    "Windows no ha dejado crear el icono.\n"
                    f"({motivo})\n"
                    "La ventana se queda como esta.")
                return

        self.config_app["modo_rendimiento"] = True
        self.config_app.guardar()
        self._en_bandeja = True
        self.withdraw()
        self._refrescar_bandeja()

    def _salir_de_bandeja(self) -> None:
        self._en_bandeja = False
        self.config_app["modo_rendimiento"] = False
        self.config_app.guardar()
        if self._bandeja is not None:
            self._bandeja.quitar()
            self._bandeja = None
        self.deiconify()
        self.lift()
        self.focus_force()

    def _estado_actual(self) -> tuple[str, str]:
        """(clave de icono, texto para el globo de la bandeja)."""
        caido = self._motor_caido()
        if caido:
            return "silenciado", "BEEP STREAM  -  FALLO\n" + caido[:100]
        if self.motor is None or not self.motor.en_marcha:
            return "parado", "BEEP STREAM  -  parado"
        if self.motor.silenciado:
            return "silenciado", "BEEP STREAM  -  MICROFONO SILENCIADO"
        if not self.motor.censor_activo:
            return "sin_censura", "BEEP STREAM  -  SIN CENSURA"

        # En segundo plano el globo es lo unico que se ve, asi que dice
        # tambien si el canal del PC sigue vivo. Que se caiga sin avisar
        # y se emita el juego sin filtrar es justo lo que no puede pasar
        # sin que nadie se entere.
        pc_en_marcha = self.motor_pc is not None and self.motor_pc.en_marcha
        if pc_en_marcha:
            fuentes_texto = (f"micro {self.motor.stats.censuras}  ·  "
                             f"PC {self.motor_pc.stats.censuras}")
        elif self.var_pc.get():
            fuentes_texto = f"micro {self.motor.stats.censuras}  ·  PC CAIDO"
        else:
            fuentes_texto = f"{self.motor.stats.censuras} censuras"

        return "activo", f"BEEP STREAM  -  activo\n{fuentes_texto}"

    def _refrescar_bandeja(self) -> None:
        if self._bandeja is None:
            return
        estado, texto = self._estado_actual()
        self._bandeja.actualizar(estado, texto)

    def _atender_bandeja(self) -> None:
        if self._bandeja is None:
            return
        for accion in self._bandeja.pendientes():
            if accion == "mostrar":
                self._salir_de_bandeja()
            elif accion == "censor":
                self._alternar_censor()
            elif accion == "mute":
                self._alternar_mute()
            elif accion == "salir":
                self._cerrar()
                return

    # ---------------------------------------------------------------
    #  Ventanas auxiliares
    # ---------------------------------------------------------------

    def _quizas_asistente(self) -> None:
        """Abre la guia la primera vez que se arranca el programa."""
        if getattr(self.config_app, "asistente_visto", False):
            return
        self._abrir_asistente()

    def _abrir_asistente(self) -> None:
        import asistente

        asistente.abrir(self)

    def _probar_beep(self) -> None:
        """Suena la censura tal y como quedaria, por los auriculares.

        Se construye al vuelo con lo elegido en la ventana, sin tocar
        config.json, para poder comparar estilos y volumenes sin
        reiniciar. Se oyen dos tramos: una palabra corta y una frase
        larga, que es donde se nota la diferencia entre los estilos.
        """
        from beeper import Beep

        frecuencia = self.config_app.frecuencia
        try:
            beep = Beep(
                self.config_app.ruta_beep, int(self.var_beep.get()), frecuencia,
                volumen=valor_volumen(self.var_volumen.get()),
                tono_hz=float(self.config_app.beep_tono_hz),
                rampa_ms=float(self.config_app.beep_rampa_ms),
                estilo=self._estilo_elegido(),
                bucle=self.config_app.modo_beep == "bucle")

            corto, largo = int(frecuencia * 0.35), int(frecuencia * 1.2)
            hueco = np.zeros(int(frecuencia * 0.4), dtype=np.float32)
            muestra = np.concatenate([
                beep.tramo(0, corto, largo_tramo=corto), hueco,
                beep.tramo(0, largo, largo_tramo=largo)])

            sd.stop()
            sd.play(muestra, frecuencia)
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("No se puede reproducir", str(error))

    def _abrir_prueba(self) -> None:
        if self.motor is not None and self.motor.en_marcha:
            messagebox.showinfo(
                "Modo prueba",
                "Para el censor antes de usar el modo prueba: necesita el "
                "microfono en exclusiva.")
            return
        VentanaPrueba(self, self._indice(self.combo_entrada, self.entradas))

    def _cerrar(self) -> None:
        if self._bandeja is not None:
            self._bandeja.quitar()
            self._bandeja = None
        if self.motor is not None:
            self.motor.parar()
        if self.motor_pc is not None:
            self.motor_pc.parar()
        self.destroy()


class VentanaPrueba(tk.Toplevel):
    """Graba unos segundos, los censura y deja comparar antes de emitir."""

    SEGUNDOS = 8

    def __init__(self, padre: Aplicacion, dispositivo) -> None:
        super().__init__(padre)
        self.padre = padre
        self.kit = padre.kit
        self.dispositivo = dispositivo
        self.original: np.ndarray | None = None
        self.censurado: np.ndarray | None = None

        self.title("Modo prueba")
        self.configure(bg=self.kit.c("fondo"))
        self.geometry("540x460")
        self.transient(padre)
        self.resizable(False, False)

        cabecera = self.kit.marco(self, "fondo")
        cabecera.pack(fill="x", padx=tm.ESPACIO["l"], pady=(tm.ESPACIO["l"], 0))
        self.kit.etiqueta(cabecera, "Modo prueba", "titulo", "texto",
                          "fondo").pack(anchor="w")
        self.kit.etiqueta(
            cabecera,
            f"Graba {self.SEGUNDOS} s, di alguna palabra de la lista y compara\n"
            "el resultado. No se emite nada: es solo para ti.",
            "cuerpo", "suave", "fondo", justify="left").pack(
            anchor="w", pady=(tm.ESPACIO["xs"], tm.ESPACIO["m"]))

        self.boton_grabar = w.Boton(self, self.kit, "GRABAR",
                                    self._grabar, "principal",
                                    rol="boton_alto", alto=13)
        self.boton_grabar.pack(fill="x", padx=tm.ESPACIO["l"],
                               pady=(0, tm.ESPACIO["s"]))

        fila = self.kit.marco(self, "fondo")
        fila.pack(fill="x", padx=tm.ESPACIO["l"], pady=(0, tm.ESPACIO["s"]))
        self.boton_original = w.Boton(fila, self.kit, "Escuchar original",
                                      lambda: self._reproducir(False), "normal",
                                      alto=10)
        self.boton_original.pack(side="left", fill="x", expand=True,
                                 padx=(0, tm.ESPACIO["s"]))
        self.boton_censurado = w.Boton(fila, self.kit, "Escuchar censurado",
                                       lambda: self._reproducir(True), "normal",
                                       alto=10)
        self.boton_censurado.pack(side="left", fill="x", expand=True)

        self.boton_guardar = w.Boton(self, self.kit,
                                     "Guardar los dos WAV en la carpeta",
                                     self._guardar, "sutil", rol="micro", alto=7)
        self.boton_guardar.pack(fill="x", padx=tm.ESPACIO["l"],
                                pady=(0, tm.ESPACIO["m"]))

        caja = self.kit.marco(self, "hundido", highlightthickness=1)
        self.kit.registrar(caja, highlightbackground="borde", highlightcolor="borde")
        caja.pack(fill="both", expand=True, padx=tm.ESPACIO["l"],
                  pady=(0, tm.ESPACIO["l"]))
        self.resultado = self.kit.registrar(
            tk.Text(caja, font=tm.fuente("mono"), relief="flat", bd=0,
                    wrap="word", padx=tm.ESPACIO["m"], pady=tm.ESPACIO["m"],
                    highlightthickness=0),
            bg="hundido", fg="suave", insertbackground="texto")
        self.resultado.pack(fill="both", expand=True)

        for boton in (self.boton_original, self.boton_censurado,
                      self.boton_guardar):
            boton.habilitar(False)
        self._escribir("Pulsa GRABAR para empezar.")

    def _escribir(self, texto: str) -> None:
        self.resultado.configure(state="normal")
        self.resultado.delete("1.0", "end")
        self.resultado.insert("end", texto)
        self.resultado.configure(state="disabled")

    def _grabar(self) -> None:
        self.boton_grabar.habilitar(False)
        self.boton_grabar.configurar(texto="GRABANDO…")
        self._escribir("Habla ahora…")
        threading.Thread(target=self._trabajo, daemon=True).start()

    def _trabajo(self) -> None:
        ajustes = self.padre.config_app
        frecuencia = ajustes.frecuencia
        try:
            grabacion = sd.rec(int(self.SEGUNDOS * frecuencia), samplerate=frecuencia,
                               channels=1, dtype="float32", device=self.dispositivo)
            sd.wait()
            self.original = grabacion[:, 0].copy()

            self.after(0, lambda: self._escribir("Analizando…"))
            self.censurado, encontradas = procesar_grabacion(
                self.original, ajustes, self.padre.detector, ajustes.ruta_modelo)

            if encontradas:
                lineas = [f"{len(encontradas)} deteccion(es):", ""]
                lineas += [
                    f"  {c.inicio:5.2f}s - {c.fin:5.2f}s   "
                    f"'{c.dicho}'  ->  {c.termino}"
                    for c in encontradas]
                lineas += ["", "Compara ORIGINAL y CENSURADO para comprobar",
                           "que el pitido cae justo encima de la palabra."]
                texto = "\n".join(lineas)
            else:
                texto = ("Sin detecciones.\n\n"
                         "Si has dicho una palabra de la lista:\n"
                         "  · acerca el microfono y sube el volumen\n"
                         "  · vocaliza un poco mas\n"
                         "  · comprueba que la palabra esta en palabras.txt\n"
                         "  · prueba el modelo grande si falla a menudo")
            self.after(0, lambda: self._terminar(texto))
        except Exception as error:  # noqa: BLE001
            mensaje = str(error)
            self.after(0, lambda: self._terminar(f"Error al grabar:\n\n{mensaje}"))

    def _terminar(self, texto: str) -> None:
        self._escribir(texto)
        self.boton_grabar.habilitar(True)
        self.boton_grabar.configurar(texto="GRABAR OTRA VEZ")
        if self.original is not None:
            for boton in (self.boton_original, self.boton_censurado,
                          self.boton_guardar):
                boton.habilitar(True)

    def _reproducir(self, censurado: bool) -> None:
        muestras = self.censurado if censurado else self.original
        if muestras is None:
            return
        try:
            sd.stop()
            sd.play(muestras, self.padre.config_app.frecuencia)
        except Exception as error:  # noqa: BLE001
            messagebox.showerror("No se puede reproducir", str(error))

    def _guardar(self) -> None:
        if self.original is None or self.censurado is None:
            return
        frecuencia = self.padre.config_app.frecuencia
        guardar_wav("prueba_original.wav", self.original, frecuencia)
        guardar_wav("prueba_censurado.wav", self.censurado, frecuencia)
        messagebox.showinfo(
            "Guardado",
            "prueba_original.wav\nprueba_censurado.wav\n\n"
            "Estan en la carpeta del programa. Borralos cuando no los necesites.")


def _ajustar_dpi() -> None:
    """Le dice a Windows que el programa sabe de pantallas escaladas.

    Sin esto, en un portatil al 125% o 150% Windows dibuja la ventana al
    100% y luego la amplia como si fuera una foto: los textos salen
    borrosos. Con la marca puesta, Tk recibe el DPI real y dibuja
    nitido.
    """
    import ctypes

    try:
        # 2 = por monitor, que es lo correcto con varias pantallas de
        # escalados distintos. Solo existe desde Windows 8.1.
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def main() -> None:
    # Las dos cosas tienen que pasar antes de crear la ventana: Tk lee
    # las tipografias disponibles y el DPI de la pantalla al arrancar y
    # ya no vuelve a mirarlos.
    fuentes.preparar()
    _ajustar_dpi()

    ventana = Aplicacion()

    # Todo lo que existe en este momento (modulos, clases, funciones,
    # los widgets de la ventana) va a seguir existiendo hasta que se
    # cierre el programa: no es basura y nunca lo sera. gc.freeze() lo
    # aparta para que el recolector deje de recorrerlo cada vez que le
    # toca una pasada a fondo. Medido con el modelo cargado, esa pasada
    # costaba entre 3,8 y 5,4 ms, y los bloques de audio son de 30 ms.
    # No cambia nada de lo que hace el programa: lo que se reserve a
    # partir de aqui (audio, reconocedores) se sigue recogiendo igual.
    gc.collect()
    gc.freeze()

    ventana.mainloop()


if __name__ == "__main__":
    main()
