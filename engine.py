"""Motor de audio: captura, retardo, censura y salida.

Tres hilos trabajan sobre el mismo flujo:

  1. Callback de ENTRADA  - escribe el microfono en la linea de retardo
                            y encola una copia para el reconocedor.
  2. Hilo de RECONOCIMIENTO - transcribe, detecta y anota que tramos de
                            audio hay que tapar.
  3. Callback de SALIDA   - lee la linea de retardo N milisegundos por
                            detras y sustituye por beep los tramos
                            anotados antes de mandarlo a VB-CABLE.

Todo se mide en "muestras absolutas": un contador que empieza en cero al
arrancar y no se reinicia. Los tiempos que devuelve Vosk se convierten a
ese mismo contador, y por eso un tramo detectado se puede localizar con
exactitud dentro del buffer aunque hayan pasado varios bloques.

El margen del retardo es lo que da seguridad: si el reconocedor tarda
300 ms en confirmar una palabra y el retardo es de 1000 ms, quedan
700 ms de sobra antes de que ese audio salga hacia el directo.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd

import dispositivos
from beeper import Beep, desde_config
from matcher import Coincidencia, Detector, fusionar

TAMANO_BLOQUE_MS = 30  # 1440 muestras a 48 kHz, multiplo exacto de 3
MARGEN_BUFFER_MS = 2000  # colchon extra de la linea de retardo
TOLERANCIA_DERIVA_MS = 150  # antes de recortar por desfase de relojes

# El segundo plano NO toca el reconocimiento a proposito: lo que apaga
# es la interfaz, que es gratis y no arriesga nada. El abaratamiento del
# reconocimiento se hizo por otra via (ver recognizer.py): 3 canales de
# 800 ms en vez de 4 de 600 y sin resultados parciales, que salio a
# mitad de coste detectando MAS. Bajar de ahi ya cuesta detecciones, y
# de eso depende no llevarse un aviso de TikTok.


class LineaRetardo:
    """Buffer circular que devuelve el audio con N muestras de retraso.

    La escritura la hace el hilo de entrada y la lectura el de salida,
    pero nunca tocan la misma zona: la lectura va siempre muy por detras
    y la capacidad tiene margen de sobra, asi que no hace falta bloqueo
    (y un bloqueo dentro de un callback de audio es justo lo que provoca
    cortes).

    Con `canales` a 1 se entra y se sale en mono (el microfono). El
    audio del PC llega en estereo y hay que conservarlo: pasarlo a mono
    aplastaria la imagen del juego y de la musica.
    """

    def __init__(self, capacidad: int, canales: int = 1) -> None:
        self._buffer = np.zeros((capacidad, canales), dtype=np.float32)
        self._capacidad = capacidad
        self._canales = canales
        self.escritas = 0

    def vaciar(self) -> None:
        """Borra el contenido y reinicia el contador.

        Se llama al arrancar: sin esto, una segunda sesion podria emitir
        restos de audio de la anterior mientras se llena el colchon.
        """
        self._buffer[:] = 0.0
        self.escritas = 0

    def escribir(self, bloque: np.ndarray) -> None:
        if bloque.ndim == 1:
            bloque = bloque[:, None]
        n = len(bloque)
        inicio = self.escritas % self._capacidad
        fin = inicio + n
        if fin <= self._capacidad:
            self._buffer[inicio:fin] = bloque
        else:
            corte = self._capacidad - inicio
            self._buffer[inicio:] = bloque[:corte]
            self._buffer[: n - corte] = bloque[corte:]
        self.escritas += n

    def leer(self, desde: int, cantidad: int) -> np.ndarray:
        inicio = desde % self._capacidad
        fin = inicio + cantidad
        if fin <= self._capacidad:
            trozo = self._buffer[inicio:fin].copy()
        else:
            corte = self._capacidad - inicio
            trozo = np.concatenate(
                [self._buffer[inicio:], self._buffer[: cantidad - corte]])
        # En mono se devuelve plano, que es como lo espera el motor del
        # microfono desde siempre.
        return trozo[:, 0] if self._canales == 1 else trozo


@dataclass
class TramoCensurado:
    inicio: int  # muestra absoluta
    fin: int
    termino: str
    dicho: str
    anunciado: bool = False


class RegistroCensura:
    """Los tramos de audio pendientes de tapar, ordenados por posicion."""

    def __init__(self) -> None:
        self._tramos: list[TramoCensurado] = []
        self._lock = threading.Lock()

    def anadir(self, inicio: int, fin: int, termino: str, dicho: str) -> bool:
        """Registra un tramo. Devuelve True si es una deteccion nueva.

        Los resultados parciales de Vosk repiten la misma palabra varias
        veces mientras se afina la transcripcion, y con tiempos que se
        corrigen ligeramente. En vez de duplicar el tramo se fusiona con
        el que ya existe, quedandose siempre con la envolvente mas ancha
        (lo que nunca deja hueco por el que se cuele la voz).
        """
        with self._lock:
            for tramo in self._tramos:
                if inicio < tramo.fin and fin > tramo.inicio:
                    tramo.inicio = min(tramo.inicio, inicio)
                    tramo.fin = max(tramo.fin, fin)
                    return False
            self._tramos.append(TramoCensurado(inicio, fin, termino, dicho))
            self._tramos.sort(key=lambda t: t.inicio)
            return True

    def solapes(self, desde: int, hasta: int) -> list[tuple[int, int, int, int]]:
        """Tramos que caen dentro de [desde, hasta).

        Devuelve (inicio_recortado, fin_recortado, inicio_del_tramo,
        fin_del_tramo). Los dos ultimos son los limites del tramo
        entero, no los del bloque: con ellos el sonido de censura sabe
        en que punto va y cuanto le queda, y puede entrar y salir con
        rampa una sola vez aunque la palabra abarque veinte bloques.
        """
        with self._lock:
            return [
                (max(t.inicio, desde), min(t.fin, hasta), t.inicio, t.fin)
                for t in self._tramos
                if t.inicio < hasta and t.fin > desde
            ]

    def purgar(self, antes_de: int) -> None:
        with self._lock:
            self._tramos = [t for t in self._tramos if t.fin > antes_de]

    def vaciar(self) -> None:
        with self._lock:
            self._tramos.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._tramos)


@dataclass
class Estadisticas:
    censuras: int = 0
    tardias: int = 0  # detectadas cuando el audio ya habia salido
    # Margen mas ajustado visto: milisegundos que sobraron entre detectar
    # la palabra y tener que emitirla. Si baja de 0, se ha escapado.
    margen_minimo_ms: float = float("inf")
    cortes_entrada: int = 0
    cortes_salida: int = 0
    ultima: str = ""
    historial: list[str] = field(default_factory=list)


class NucleoCensor:
    """Lo comun al censor del microfono y al del audio del PC.

    Los dos hacen exactamente lo mismo con el sonido — retrasarlo,
    transcribirlo, anotar que tramos sobran y taparlos — y solo se
    diferencian en por donde entra y por donde sale. Todo lo demas vive
    aqui, para que un arreglo en la deteccion valga para los dos a la
    vez y no haya que acordarse de tocarlo en dos sitios.

    `canales` es 1 para el microfono y 2 para el audio del PC, que llega
    en estereo y hay que conservarlo. `etiqueta` es lo que se antepone a
    los avisos del registro, para saber cual de los dos esta hablando.
    """

    def __init__(self, config, detector: Detector, al_registrar=None,
                 canales: int = 1, etiqueta: str = "",
                 alternativas: int = 0, realce=None) -> None:
        self.config = config
        self.detector = detector
        self._al_registrar = al_registrar or (lambda mensaje, nivel="info": None)
        self.etiqueta = etiqueta

        self.frecuencia = config.frecuencia
        self.bloque = int(self.frecuencia * TAMANO_BLOQUE_MS / 1000)
        self.muestras_retardo = config.muestras_retardo

        capacidad = self.muestras_retardo + self.frecuencia * MARGEN_BUFFER_MS // 1000
        self.linea = LineaRetardo(capacidad, canales)
        self.canales = canales
        self.registro = RegistroCensura()
        self.stats = Estadisticas()
        # Cuantas hipotesis se le piden a Vosk y si hay que realzar la
        # copia que se transcribe. Los dos van a cero en el microfono,
        # que se oye bien de por si, y se usan en el audio del PC.
        self.alternativas = int(alternativas)
        self.realce = realce
        # Motivo por el que se ha caido el reconocimiento, si se cae.
        self.fallo = ""

        self.beep = desde_config(config)
        self._bucle_beep = config.modo_beep == "bucle"

        self._margen_antes = config.muestras(config.margen_antes_ms)
        self._margen_despues = config.muestras(config.margen_despues_ms)
        self._tolerancia = config.muestras(TOLERANCIA_DERIVA_MS)

        self.censor_activo = bool(config.censor_activo)
        self.rendimiento = bool(getattr(config, "modo_rendimiento", False))
        self.silenciado = False
        self.nivel = 0.0
        # Pico mas alto visto desde que arranco. Sirve para detectar un
        # microfono silenciado, que abre sin error pero no da senal.
        self.nivel_maximo = 0.0
        self.arrancado_en = 0.0

        self._lectura = 0
        self._colchon_lleno = False
        # Detecciones ya anunciadas. Sin esto, una palabra que se
        # detecta tarde se vuelve a detectar en cada resultado parcial
        # y llena el registro con cientos de lineas identicas.
        self._anunciadas: dict[tuple[int, str], int] = {}
        self._cola = queue.Queue(maxsize=200)
        self._parar = threading.Event()
        self._hilo = None
        self._entrada = None
        self._salida = None
        self._reconocedor = None

    # ---------------------------------------------------------------
    #  Arranque y parada de la parte comun
    # ---------------------------------------------------------------

    def _arrancar_nucleo(self) -> None:
        """Deja el reconocimiento limpio y en marcha."""
        from recognizer import Reconocedor

        self._reconocedor = Reconocedor(
            self.config.ruta_modelo, self.config.confianza_minima,
            alternativas=self.alternativas,
        )
        if self.realce is not None:
            self.realce.reiniciar()
        self._lectura = 0
        self._colchon_lleno = False
        self.linea.vaciar()
        self.registro.vaciar()
        self._anunciadas.clear()
        self._parar.clear()
        self.fallo = ""
        self.nivel_maximo = 0.0
        self.arrancado_en = time.time()

        self._hilo = threading.Thread(target=self._bucle_reconocimiento, daemon=True)
        self._hilo.start()

    def _parar_nucleo(self) -> None:
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=1.5)
            self._hilo = None

        self._reconocedor = None
        self.registro.vaciar()
        while not self._cola.empty():
            try:
                self._cola.get_nowait()
            except queue.Empty:
                break

    def _encolar(self, mono: np.ndarray) -> None:
        """Pasa un bloque al reconocedor sin bloquear el hilo de audio.

        Aqui es donde se realza, si toca: lo que se emite ya se ha
        escrito en la linea de retardo y no se toca nunca.
        """
        if self.realce is not None:
            mono = self.realce.procesar(mono)
        try:
            self._cola.put_nowait(mono)
        except queue.Full:
            # El reconocedor no da abasto. Se descarta este bloque para no
            # bloquear el callback: es preferible perder una ventana de
            # analisis a provocar un corte en el audio del directo.
            pass

    def _tapar(self, muestras: np.ndarray, inicio: int, fin: int) -> None:
        """Sustituye por el sonido de censura los tramos anotados.

        Trabaja sobre el bloque ya sacado de la linea de retardo, en
        mono o en estereo. En estereo el mismo sonido va a los dos
        canales: una censura que sonara solo por un lado cantaria mas
        que la propia palabrota.
        """
        for tramo_ini, tramo_fin, origen, final in self.registro.solapes(inicio, fin):
            desde = tramo_ini - inicio
            hasta = tramo_fin - inicio
            pitido = self.beep.tramo(
                tramo_ini - origen, hasta - desde, self._bucle_beep, final - origen)
            if muestras.ndim == 1:
                muestras[desde:hasta] = pitido
            else:
                muestras[desde:hasta, :] = pitido[:, None]

    @property
    def en_marcha(self) -> bool:
        """Si el reconocimiento esta vivo de verdad.

        No basta con que el hilo exista: si se hubiera muerto, el audio
        seguiria saliendo al directo sin filtrar y la ventana estaria
        diciendo que todo va bien.
        """
        return self._hilo is not None and self._hilo.is_alive()

    @property
    def retardo_real_ms(self) -> float:
        if not self._colchon_lleno:
            return 0.0
        return 1000.0 * (self.linea.escritas - self._lectura) / self.frecuencia

    # ---------------------------------------------------------------
    #  Reconocimiento
    # ---------------------------------------------------------------

    def _bucle_reconocimiento(self) -> None:
        """Transcribe y anota, pase lo que pase.

        Este hilo no se puede morir. El audio sigue saliendo al directo
        aunque el reconocimiento se caiga, asi que un fallo aqui no seria
        un programa roto: seria un programa que parece funcionar mientras
        emite todo sin censurar. Por eso cada vuelta va protegida y, si
        aun asi se rompe, queda constancia en `fallo` para que la ventana
        y el icono de la bandeja lo canten.
        """
        try:
            while not self._parar.is_set():
                try:
                    bloque = self._cola.get(timeout=0.2)
                except queue.Empty:
                    continue

                try:
                    palabras, _ = self._reconocedor.alimentar(bloque)
                    if palabras:
                        for coincidencia in self.detector.buscar(palabras):
                            self._anotar(coincidencia)
                        self.registro.purgar(self._lectura - self.frecuencia)
                except Exception as error:  # noqa: BLE001
                    self._al_registrar(
                        f"{self.etiqueta}Error de reconocimiento: {error}", "error")
        except BaseException as error:  # noqa: BLE001
            self.fallo = str(error) or error.__class__.__name__
            self._al_registrar(
                f"{self.etiqueta}EL RECONOCIMIENTO SE HA CAÍDO ({self.fallo}). "
                "El audio esta saliendo SIN CENSURAR: para y vuelve a iniciar.",
                "error")
            raise

    def _anotar(self, coincidencia: Coincidencia) -> None:
        inicio = int(coincidencia.inicio * self.frecuencia) - self._margen_antes
        fin = int(coincidencia.fin * self.frecuencia) + self._margen_despues
        inicio = max(0, inicio)

        # Clave por posicion (en decimas de segundo) y termino: la misma
        # palabra dicha dos veces son dos detecciones, la misma repetida
        # por resultados parciales es una sola.
        clave = (inicio // (self.frecuencia // 10), coincidencia.termino)
        ya_estaba = clave in self._anunciadas
        self._anunciadas[clave] = self._lectura
        if len(self._anunciadas) > 300:
            viejo = self._lectura - self.frecuencia * 30
            self._anunciadas = {
                k: v for k, v in self._anunciadas.items() if v > viejo
            }

        if not self.registro.anadir(inicio, fin, coincidencia.termino, coincidencia.dicho):
            return  # ya estaba anotado por un resultado parcial anterior
        if ya_estaba:
            return  # se emitio hace poco: no repetir el aviso

        self.stats.censuras += 1
        self.stats.ultima = coincidencia.termino

        margen_ms = 1000.0 * (inicio - self._lectura) / self.frecuencia
        self.stats.margen_minimo_ms = min(self.stats.margen_minimo_ms, margen_ms)
        if margen_ms < 0:
            # El audio ya habia salido. Es la senal inequivoca de que el
            # retardo configurado se queda corto para quien esta hablando.
            self.stats.tardias += 1
            self._al_registrar(
                f"{self.etiqueta}TARDE: '{coincidencia.termino}' detectado "
                f"{abs(margen_ms):.0f} ms después de emitir. Sube el retardo.",
                "error",
            )
        else:
            self._al_registrar(
                f"{self.etiqueta}CENSURANDO: '{coincidencia.termino}' "
                f"(oído: '{coincidencia.dicho}', margen {margen_ms:.0f} ms)",
                "censura",
            )

    # ---------------------------------------------------------------
    #  Salida
    # ---------------------------------------------------------------

    def _emitir(self, frames: int):
        """Saca `frames` muestras ya censuradas de la linea de retardo.

        Devuelve None mientras no haya nada que emitir: al arrancar,
        porque el colchon todavia se esta llenando, y en marcha si la
        entrada se ha quedado corta. En los dos casos lo que toca es
        silencio, y quien llame se encarga de escribirlo.
        """
        disponible = self.linea.escritas - self._lectura

        if not self._colchon_lleno:
            # Al arrancar hay que dejar que el buffer se llene hasta el
            # retardo elegido; hasta entonces sale silencio.
            if disponible < self.muestras_retardo:
                return None
            self._colchon_lleno = True

        if disponible < frames:
            self.stats.cortes_salida += 1
            return None

        if disponible > self.muestras_retardo + self._tolerancia:
            # Los relojes de la entrada y de la salida no son el mismo y
            # van separandose. Se recorta el exceso para que el retardo
            # no crezca durante el directo.
            self._lectura += disponible - self.muestras_retardo

        inicio = self._lectura
        fin = inicio + frames
        muestras = self.linea.leer(inicio, frames)

        if self.censor_activo:
            self._tapar(muestras, inicio, fin)

        if self.silenciado:
            muestras[:] = 0.0

        self._lectura = fin
        np.clip(muestras, -1.0, 1.0, out=muestras)
        return muestras


class MotorCensor(NucleoCensor):
    """Une microfono, reconocimiento, censura y salida."""

    def __init__(self, config, detector: Detector, al_registrar=None) -> None:
        super().__init__(config, detector, al_registrar, canales=1)

    # ---------------------------------------------------------------
    #  Entrada
    # ---------------------------------------------------------------

    def _callback_entrada(self, indata, frames, tiempo, estado) -> None:
        if estado.input_overflow:
            self.stats.cortes_entrada += 1

        mono = indata[:, 0].astype(np.float32, copy=True)
        self.linea.escribir(mono)
        # np.dot es la suma de cuadrados sin crear el array intermedio,
        # como ya se hacia en el canal del PC. Dentro de un callback de
        # audio importa menos lo que se tarda que lo que se reserva: un
        # array de 1440 muestras 33 veces por segundo es basura que
        # alguien tiene que recoger, y el recolector no avisa de cuando.
        self.nivel = float(np.sqrt(np.dot(mono, mono) / len(mono)))
        pico = float(np.max(np.abs(mono)))
        if pico > self.nivel_maximo:
            self.nivel_maximo = pico

        self._encolar(mono)

    # ---------------------------------------------------------------
    #  Salida
    # ---------------------------------------------------------------

    def _callback_salida(self, outdata, frames, tiempo, estado) -> None:
        if estado.output_underflow:
            self.stats.cortes_salida += 1

        muestras = self._emitir(frames)
        if muestras is None:
            outdata[:] = 0
            return

        if outdata.shape[1] == 1:
            outdata[:, 0] = muestras
        else:
            outdata[:] = muestras[:, None]  # mismo mono en los dos canales

    # ---------------------------------------------------------------
    #  Control
    # ---------------------------------------------------------------

    def iniciar(self) -> None:
        if self._hilo is not None:
            return

        canales = max(1, min(int(self.config.canales_salida), 2))

        # Un nombre como "CABLE Input" coincide con varias APIs de
        # Windows a la vez; hay que quedarse con una concreta.
        entrada = dispositivos.resolver(self.config.dispositivo_entrada, entrada=True)
        destino = dispositivos.resolver(self.config.dispositivo_salida, entrada=False)

        self._arrancar_nucleo()

        # Se abre probando el aparato elegido y, si falla, sus copias en
        # las otras APIs de Windows. Un casco inalambrico que se ha
        # dormido, o que otro programa tiene cogido, falla por una API y
        # abre por otra: sin esto habria que reiniciar el programa.
        try:
            self._entrada, usada_entrada = dispositivos.abrir(
                lambda idx: sd.InputStream(
                    device=idx,
                    channels=1,
                    samplerate=self.frecuencia,
                    blocksize=self.bloque,
                    dtype="float32",
                    callback=self._callback_entrada,
                ),
                entrada,
                entrada=True,
                que_es="el micrófono",
            )

            self._salida, usada_salida = dispositivos.abrir(
                lambda idx: sd.OutputStream(
                    device=idx,
                    channels=canales,
                    samplerate=self.frecuencia,
                    blocksize=self.bloque,
                    dtype="float32",
                    callback=self._callback_salida,
                ),
                destino,
                entrada=False,
                que_es="la salida hacia VB-CABLE",
            )
        except Exception:
            # Si el segundo flujo falla hay que soltar el primero, o el
            # microfono se queda cogido hasta cerrar el programa.
            self.parar()
            raise

        if usada_entrada != entrada:
            self._al_registrar(
                f"El micrófono elegido no abría; se usa "
                f"{dispositivos.describir(usada_entrada)}.",
                "error",
            )
        if usada_salida != destino:
            self._al_registrar(
                f"La salida elegida no abría; se usa "
                f"{dispositivos.describir(usada_salida)}.",
                "error",
            )

        self._al_registrar(
            f"Censor en marcha. Retardo {self.config.retardo_ms} ms, "
            f"{self.detector.total_terminos} términos cargados.",
            "ok",
        )

    def parar(self) -> None:
        self._parar.set()

        for flujo in (self._entrada, self._salida):
            if flujo is not None:
                try:
                    flujo.stop()
                    flujo.close()
                except sd.PortAudioError:
                    pass
        self._entrada = self._salida = None

        self._parar_nucleo()
        self._al_registrar("Censor detenido.", "info")


def procesar_grabacion(
    muestras: np.ndarray, config, detector: Detector, ruta_modelo: str
) -> tuple[np.ndarray, list[Coincidencia]]:
    """Censura una grabacion ya existente. Es la base del modo prueba.

    Usa exactamente el mismo detector y el mismo beep que el directo,
    para que lo que oigas al probar sea lo que va a salir por el stream.
    """
    from recognizer import Reconocedor

    reconocedor = Reconocedor(ruta_modelo, config.confianza_minima)
    frecuencia = config.frecuencia
    bloque = int(frecuencia * TAMANO_BLOQUE_MS / 1000)

    encontradas: list[Coincidencia] = []
    for i in range(0, len(muestras), bloque):
        palabras, _ = reconocedor.alimentar(muestras[i : i + bloque])
        encontradas.extend(detector.buscar(palabras))
    encontradas.extend(detector.buscar(reconocedor.vaciar()))
    encontradas = fusionar(encontradas)

    beep = desde_config(config)
    salida = muestras.copy()
    margen_antes = config.muestras(config.margen_antes_ms)
    margen_despues = config.muestras(config.margen_despues_ms)

    for c in encontradas:
        inicio = max(0, int(c.inicio * frecuencia) - margen_antes)
        fin = min(len(salida), int(c.fin * frecuencia) + margen_despues)
        if fin > inicio:
            salida[inicio:fin] = beep.tramo(
                0, fin - inicio, config.modo_beep == "bucle", fin - inicio)

    return salida, encontradas
