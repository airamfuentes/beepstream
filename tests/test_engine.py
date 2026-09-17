"""Pruebas del motor de audio. Se ejecuta con:  py -3.11 tests/test_engine.py

No abre microfono ni altavoces: valida las estructuras de datos y el
procesado de senal, que es donde un fallo silencioso arruinaria el
directo (un buffer mal indexado suena a chasquido, un decimador con la
fase rota destroza el reconocimiento).
"""

import os
import sys

# Se ejecutan desde la raiz del proyecto (py -3.11 tests/test_engine.py),
# asi que hay que meter esa raiz en la ruta de importacion: Python solo
# pone ahi la carpeta del propio fichero.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile

import numpy as np

from beeper import VOLUMEN, Beep, generar_tono, guardar_wav
import escritorio
from engine import LineaRetardo, NucleoCensor, RegistroCensura
from matcher import Detector
from recognizer import Decimador

fallos = 0


def comprobar(etiqueta, condicion, detalle=""):
    global fallos
    if not condicion:
        fallos += 1
    print(f"  {'OK  ' if condicion else 'FALLO'}  {etiqueta}")
    if not condicion and detalle:
        print(f"         {detalle}")

print("\n== LINEA DE RETARDO ==")
linea = LineaRetardo(1000)
linea.escribir(np.arange(300, dtype=np.float32))
comprobar("contador de escritura", linea.escritas == 300)
comprobar("lectura desde el principio", np.array_equal(linea.leer(0, 300), np.arange(300)))
comprobar("lectura parcial", np.array_equal(linea.leer(100, 50), np.arange(100, 150)))

# Dar la vuelta al buffer circular es donde aparecen los fallos de indice.
linea = LineaRetardo(100)
for i in range(5):
    linea.escribir(np.full(30, i, dtype=np.float32))
comprobar("escritas tras dar la vuelta", linea.escritas == 150)
comprobar("lee el ultimo bloque", np.all(linea.leer(120, 30) == 4))
comprobar("lee a caballo del corte", np.array_equal(linea.leer(85, 20), np.concatenate([np.full(5, 2), np.full(15, 3)])))

linea = LineaRetardo(1000)
linea.escribir(np.arange(600, dtype=np.float32))
comprobar("escritura a caballo del corte", np.array_equal(linea.leer(0, 600), np.arange(600)))
linea.escribir(np.arange(600, 1200, dtype=np.float32))
comprobar("segunda vuelta correcta", np.array_equal(linea.leer(400, 700), np.arange(400, 1100)))

print("\n== RETARDO EFECTIVO ==")
linea = LineaRetardo(10000)
retardo = 480  # 10 ms a 48 kHz
for i in range(10):
    linea.escribir(np.full(100, i, dtype=np.float32))
lectura = linea.escritas - retardo
comprobar("el retardo devuelve audio antiguo", linea.leer(lectura, 10)[0] == 5.0,
          f"obtenido {linea.leer(lectura, 10)[0]}")

print("\n== REGISTRO DE CENSURA ==")
reg = RegistroCensura()
comprobar("primera deteccion es nueva", reg.anadir(1000, 2000, "puta", "puta") is True)
comprobar("la misma repetida no lo es", reg.anadir(1000, 2000, "puta", "puta") is False)
comprobar("solape parcial se fusiona", reg.anadir(1500, 2500, "puta", "puta") is False)
comprobar("sigue habiendo un solo tramo", len(reg) == 1)
solapes = reg.solapes(0, 5000)
comprobar("el tramo se ha ensanchado", solapes[0][:2] == (1000, 2500), str(solapes))
comprobar("tramo lejano es nuevo", reg.anadir(9000, 9500, "mierda", "mierda") is True)
comprobar("ahora hay dos tramos", len(reg) == 2)

print("\n== SOLAPES CON EL BLOQUE DE SALIDA ==")
reg = RegistroCensura()
reg.anadir(1000, 2000, "x", "x")
comprobar("bloque anterior: sin solape", reg.solapes(0, 500) == [])
comprobar("bloque posterior: sin solape", reg.solapes(3000, 4000) == [])
# Cada solape lleva detras los limites del tramo COMPLETO (1000, 2000),
# que son los que necesita el sonido de censura para colocar sus rampas.
comprobar("bloque contenido", reg.solapes(1200, 1400) == [(1200, 1400, 1000, 2000)])
comprobar("recorte por la izquierda", reg.solapes(500, 1500) == [(1000, 1500, 1000, 2000)])
comprobar("recorte por la derecha", reg.solapes(1500, 2500) == [(1500, 2000, 1000, 2000)])
comprobar("purga lo ya emitido", (reg.purgar(2500), len(reg) == 0)[1])

print("\n== DECIMADOR 48k -> 16k ==")
dec = Decimador()
salida = dec.procesar(np.zeros(1440, dtype=np.float32))
comprobar("1440 muestras dan 480", len(salida) == 480, f"dio {len(salida)}")

# Bloques de tamano irregular: la rejilla de muestreo no debe desalinearse.
dec = Decimador()
total = sum(len(dec.procesar(np.zeros(n, dtype=np.float32))) for n in [100, 250, 71, 1000, 33])
comprobar("bloques irregulares mantienen la fase", abs(total - 1454 // 3) <= 1,
          f"esperado ~484, obtenido {total}")

# Un tono de 1 kHz debe seguir siendo 1 kHz despues de decimar.
dec = Decimador()
t = np.arange(48000, dtype=np.float32) / 48000
tono = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
decimado = np.concatenate([dec.procesar(tono[i:i + 1440]) for i in range(0, len(tono), 1440)])
espectro = np.abs(np.fft.rfft(decimado[2000:2000 + 8192]))
pico_hz = np.fft.rfftfreq(8192, 1 / 16000)[np.argmax(espectro)]
comprobar("el tono conserva su frecuencia", abs(pico_hz - 1000) < 15, f"pico en {pico_hz:.0f} Hz")

# Una frecuencia por encima de Nyquist debe quedar atenuada, no replegada.
dec = Decimador()
agudo = np.sin(2 * np.pi * 11000 * t).astype(np.float32)
dec_agudo = np.concatenate([dec.procesar(agudo[i:i + 1440]) for i in range(0, len(agudo), 1440)])
comprobar("filtro antialias funcionando",
          np.sqrt(np.mean(dec_agudo**2)) < 0.02,
          f"energia residual {np.sqrt(np.mean(dec_agudo ** 2)):.4f}")

print("\n== BEEP ==")
tono = generar_tono(250, 48000)
comprobar("duracion correcta", len(tono) == 12000, f"dio {len(tono)}")
comprobar("arranca en silencio (rampa)", abs(tono[0]) < 0.01)
comprobar("termina en silencio (rampa)", abs(tono[-1]) < 0.01)
comprobar("tiene senal en medio", np.max(np.abs(tono[5000:7000])) > VOLUMEN * 0.9)
comprobar("y no pasa del volumen pedido", np.max(np.abs(tono)) <= VOLUMEN + 1e-6)

ruta_inexistente = os.path.join(tempfile.gettempdir(), "beepstream_test_tono.wav")
if os.path.exists(ruta_inexistente):
    os.remove(ruta_inexistente)
beep = Beep(ruta_inexistente, 250, 48000)
comprobar("sin estilo se genera el tono", beep.origen == "generado (tono)")
comprobar("bucle cubre tramos largos", len(beep.tramo(0, 50000, bucle=True)) == 50000)
comprobar("el bucle no deja silencios",
          np.max(np.abs(beep.tramo(0, 50000, True)[40000:])) > VOLUMEN * 0.5)
comprobar("modo fijo rellena con silencio", np.all(beep.tramo(0, 50000, False)[13000:] == 0))

# El estilo "archivo" es el unico que mira el disco, y si no lo hay
# tiene que seguir sonando algo: quedarse mudo seria dejar pasar la
# palabrota entera.
sin_fichero = Beep(ruta_inexistente, 250, 48000, estilo="archivo")
comprobar("archivo que no existe cae al tono", sin_fichero.origen == "generado (no hay beep.wav)")
comprobar("y aun asi suena", np.max(np.abs(sin_fichero.tramo(0, 5000, True))) > 0.01)

guardar_wav(ruta_inexistente, generar_tono(250, 48000), 48000)
comprobar("si existe, se usa el fichero",
          Beep(ruta_inexistente, 250, 48000, estilo="archivo").origen.startswith("archivo"))
os.remove(ruta_inexistente)

print("")
print("== ESTILOS SOSTENIDOS (el shhh del directo) ==")
shhh = Beep("", 250, 48000, volumen=VOLUMEN, estilo="shhh", rampa_ms=20)
comprobar("es sostenido, no repetido", shhh.sostenido is True)
comprobar("no pasa del volumen pedido", np.max(np.abs(shhh.muestras)) <= VOLUMEN + 1e-6)

# Lo que se quiere evitar: que una frase larga suene "bip-bip-bip". Se
# renderiza un tramo de 1,5 s por bloques, igual que lo hace el motor, y
# se mira que por dentro no haya bajones de volumen.
largo = 72000
bloques = [shhh.tramo(i, 1440, True, largo) for i in range(0, largo, 1440)]
render = np.concatenate(bloques)
comprobar("el tramo se cubre entero", len(render) == largo)

medio = render[4800:largo - 4800]
ventanas = medio[: (len(medio) // 4800) * 4800].reshape(-1, 4800)
energia = np.sqrt((ventanas ** 2).mean(axis=1))
comprobar("energia pareja de principio a fin del tramo",
          float(energia.min()) > float(energia.max()) * 0.70,
          f"min {energia.min():.4f} max {energia.max():.4f}")

comprobar("entra con rampa", abs(float(render[0])) < 0.01)
comprobar("sale con rampa", abs(float(render[-1])) < 0.01)
comprobar("y en medio suena", float(np.max(np.abs(medio))) > VOLUMEN * 0.4)

# El empalme del lecho consigo mismo no debe dar un chasquido: se mira
# el salto de muestra a muestra en la vuelta.
vuelta = shhh.tramo(len(shhh) - 240, 480, True, 200000)
saltos = np.abs(np.diff(vuelta))
comprobar("el lecho empalma sin chasquido",
          float(saltos.max()) < VOLUMEN * 0.5,
          f"salto maximo {saltos.max():.4f}")

# Un tramo corto no puede quedarse en nada por culpa de las rampas.
corto = shhh.tramo(0, 2400, True, 2400)
comprobar("un tramo corto tambien suena", float(np.max(np.abs(corto))) > VOLUMEN * 0.3)


def periodicidad(estilo: str, largo: int = 144000) -> float:
    """Cuanto se repite a si mismo el sonido dentro de un tramo largo.

    Es la medida objetiva del bip-bip: se saca la envolvente y se
    autocorrelaciona. Un sonido que se encadena cada 150 ms da un pico
    altisimo ahi; uno sostenido no da pico en ninguna parte.
    """
    b = Beep("", 150, 48000, volumen=VOLUMEN, estilo=estilo)
    render = np.concatenate(
        [b.tramo(i, 1440, True, largo) for i in range(0, largo, 1440)])
    x = np.abs(render[9600:largo - 9600])
    x = np.convolve(x, np.ones(96, dtype=np.float32) / 96, mode="same")
    x = x - x.mean()
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    return float((ac / ac[0])[1200:40000].max())   # de 25 a 830 ms

repite = periodicidad("shhh")
comprobar("el shhh no se repite a si mismo", repite < 0.40, f"autocorrelacion {repite:.2f}")
clasico = periodicidad("tono")
comprobar("y la medida distingue: el pitido clasico si se repite",
          clasico > 0.70, f"autocorrelacion {clasico:.2f}")
comprobar("continuidad entre bloques",
          np.array_equal(beep.tramo(0, 12000, True)[6000:], beep.tramo(6000, 6000, True)))

print("\n== SUSTITUCION DE AUDIO ==")
voz = np.ones(48000, dtype=np.float32) * 0.5
salida = voz.copy()
salida[10000:20000] = beep.tramo(0, 10000, True)
comprobar("antes del tramo queda la voz", np.all(salida[:10000] == 0.5))
comprobar("dentro del tramo no queda voz", not np.any(salida[10000:20000] == 0.5))
comprobar("despues del tramo vuelve la voz", np.all(salida[20000:] == 0.5))

print("")
print("== AUDIO DEL PC: LINEA ESTEREO Y MEZCLA ==")

# La linea del audio del PC guarda dos canales; la del microfono, uno.
# Los dos tienen que devolver lo suyo sin que el otro se entere.
estereo = LineaRetardo(1000, canales=2)
bloque = np.stack([np.arange(100, dtype=np.float32),
                   np.arange(100, dtype=np.float32) + 500], axis=1)
estereo.escribir(bloque)
leido = estereo.leer(0, 100)
comprobar("la linea estereo devuelve (n, 2)", leido.shape == (100, 2), str(leido.shape))
comprobar("y no mezcla los canales",
          np.array_equal(leido, bloque), "los canales han cambiado")

mono = LineaRetardo(1000)
mono.escribir(np.arange(50, dtype=np.float32))
comprobar("la de mono sigue devolviendo plano", mono.leer(0, 50).shape == (50,))

# Mezcla de 7.1 a estereo: el centro se reparte, el subgraves se tira.
canal = np.zeros((4, 8), dtype=np.float32)
canal[:, 0] = 1.0     # frontal izq
canal[:, 1] = 2.0     # frontal der
canal[:, 2] = 1.0     # centro
canal[:, 3] = 9.0     # subgraves: no debe aparecer
mezcla = escritorio.mezclar_estereo(canal)
comprobar("la voz del centro llega a los dos lados",
          abs(mezcla[0, 0] - 1.707) < 0.01 and abs(mezcla[0, 1] - 2.707) < 0.01,
          str(mezcla[0]))
comprobar("el subgraves no entra en la mezcla", float(mezcla.max()) < 5.0, str(mezcla[0]))
comprobar("el estereo normal pasa intacto",
          np.array_equal(escritorio.mezclar_estereo(
              np.array([[0.3, 0.7]], dtype=np.float32)),
              np.array([[0.3, 0.7]], dtype=np.float32)))
comprobar("el mono se abre a los dos canales",
          np.array_equal(escritorio.mezclar_estereo(
              np.ones((2, 1), dtype=np.float32)),
              np.ones((2, 2), dtype=np.float32)))

# El sonido de censura tiene que ir igual por los dos canales: uno solo
# cantaria mas que la propia palabrota.
nucleo = NucleoCensor.__new__(NucleoCensor)
nucleo.registro = RegistroCensura()
nucleo.registro.anadir(100, 300, "x", "x")
nucleo.beep = Beep("", 150, 48000, volumen=VOLUMEN, estilo="shhh")
nucleo._bucle_beep = True
audio = np.ones((400, 2), dtype=np.float32) * 0.5
nucleo._tapar(audio, 0, 400)
comprobar("en estereo se tapa por los dos lados",
          np.array_equal(audio[100:300, 0], audio[100:300, 1]))
comprobar("y solo dentro del tramo",
          np.all(audio[:100] == 0.5) and np.all(audio[300:] == 0.5))

print("")
print("== REALCE DE LA COPIA QUE SE TRANSCRIBE ==")
from recognizer import Realce, _Canal  # noqa: E402

t = np.arange(1440, dtype=np.float32) / 48000
voz = np.sin(2 * np.pi * 300 * t).astype(np.float32)


def estable(realce, bloque, vueltas=60):
    """Deja que la ganancia llegue a su sitio: sube poco a poco."""
    for _ in range(vueltas):
        salida = realce.procesar(bloque)
    return salida

floja = voz * 0.01                       # ~ -43 dBFS
subida = estable(Realce(), floja)
comprobar("la voz floja se sube", np.max(np.abs(subida)) > np.max(np.abs(floja)) * 4,
          f"de {np.max(np.abs(floja)):.4f} a {np.max(np.abs(subida)):.4f}")
comprobar("pero sin pasarse de escala", np.max(np.abs(subida)) <= 1.0)

fuerte = voz * 0.5
comprobar("lo que ya suena bien no se toca",
          np.allclose(estable(Realce(), fuerte), fuerte),
          "ha cambiado un bloque que no lo necesitaba")

# Amplificar ruido de fondo es la via rapida a que el modelo se invente
# palabras, y cada palabra inventada es un pitido sobre algo que nadie
# ha dicho.
rng = np.random.default_rng(11)
suelo = (rng.standard_normal(1440).astype(np.float32) * 0.0005)
comprobar("el ruido de fondo no se amplifica",
          np.allclose(estable(Realce(), suelo), suelo),
          "ha amplificado por debajo del suelo")

realce = Realce()
realce.procesar(floja)
realce.reiniciar()
comprobar("al reiniciar vuelve a ganancia 1", realce.ganancia == 1.0)

print("")
print("== HIPOTESIS MULTIPLES DE VOSK ==")
import json as _json  # noqa: E402

sencillo = _json.dumps({"result": [{"word": "puta", "start": 1.0, "end": 1.3}]})
comprobar("formato de siempre: se lee igual",
          [p["word"] for p in _Canal._palabras(sencillo)] == ["puta"])

varias = _json.dumps({"alternatives": [
    {"text": "hijos de fruta", "result": [
        {"word": "hijos", "start": 1.0, "end": 1.3},
        {"word": "de", "start": 1.3, "end": 1.4},
        {"word": "fruta", "start": 1.4, "end": 1.8}]},
    {"text": "hijos de puta", "result": [
        {"word": "hijos", "start": 1.0, "end": 1.3},
        {"word": "de", "start": 1.3, "end": 1.4},
        {"word": "puta", "start": 1.4, "end": 1.8}]},
]})
leidas = _Canal._palabras(varias)
textos = [p["word"] for p in leidas]
comprobar("la palabrota de la segunda hipotesis aparece", "puta" in textos, str(textos))
comprobar("y no se repiten las que ya estaban",
          textos.count("hijos") == 1 and textos.count("de") == 1, str(textos))
comprobar("salen ordenadas por tiempo",
          [p["start"] for p in leidas] == sorted(p["start"] for p in leidas))
comprobar("sin alternativas no se inventa nada", _Canal._palabras("{}") == [])

print("")
print("== EL RECONOCIMIENTO NO SE PUEDE MORIR ==")
import threading  # noqa: E402
import time as _time  # noqa: E402

import config as _cfg  # noqa: E402
import rutas as _rutas  # noqa: E402

_rutas.preparar()


class _ReconocedorQueFalla:
    """Simula que Vosk (o el detector) revienta en pleno directo."""

    def __init__(self):
        self.vueltas = 0

    def alimentar(self, bloque):
        self.vueltas += 1
        raise RuntimeError("kaboom")

    def vaciar(self):
        return []

avisos = []
_conf = _cfg.cargar()
nucleo = NucleoCensor(_conf, Detector(["puta"], "balanceado", []),
                      lambda m, n="info": avisos.append((n, m)))
nucleo._reconocedor = _ReconocedorQueFalla()
nucleo._parar.clear()
nucleo._hilo = threading.Thread(target=nucleo._bucle_reconocimiento, daemon=True)
nucleo._hilo.start()

for _ in range(5):
    nucleo._encolar(np.zeros(1440, dtype=np.float32))
_time.sleep(0.6)

comprobar("el hilo sigue vivo tras cinco errores", nucleo._hilo.is_alive())
comprobar("y lo ha contado en el registro",
          sum(1 for nivel, _ in avisos if nivel == "error") >= 1,
          str(avisos[:2]))
comprobar("en_marcha dice que si mientras vive", nucleo.en_marcha is True)
comprobar("no se ha marcado como caido", nucleo.fallo == "")

nucleo._parar.set()
nucleo._hilo.join(timeout=2.0)
comprobar("para cuando se le pide", not nucleo._hilo.is_alive())
comprobar("y entonces en_marcha dice que no", nucleo.en_marcha is False)

print("\n" + "=" * 54)
print(f"  {fallos} FALLO(S)" if fallos else "  TODO CORRECTO")
print("=" * 54 + "\n")
raise SystemExit(1 if fallos else 0)
