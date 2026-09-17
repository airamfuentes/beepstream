<p align="center">
  <img src="docs/banner.png" alt="BEEP STREAM" width="100%">
</p>

<p align="center">
  <strong>Real-time profanity censor for live streams.</strong><br>
  Hears what you say, recognises the words you chose, and covers them with a tone
  before they reach the broadcast.
</p>

<p align="center">
  <img alt="Windows 10+" src="https://img.shields.io/badge/Windows-10%2B-111?style=flat-square">
  <img alt="Python 3.11" src="https://img.shields.io/badge/Python-3.11-111?style=flat-square">
  <img alt="Offline" src="https://img.shields.io/badge/100%25-offline-111?style=flat-square">
  <img alt="MIT" src="https://img.shields.io/badge/licence-MIT-111?style=flat-square">
</p>

<p align="center">
  <a href="#download">Download</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#tech-stack">Tech stack</a> ·
  <a href="#features">Features</a> ·
  <a href="#from-source">From source</a> ·
  <a href="README.es.md">🇪🇸 Español</a>
</p>

---

Swearing on air can cost a streamer their channel, and there is no post-production
when the broadcast *is* the product. BEEP STREAM sits between the microphone and
OBS: it buffers your voice for a second and a half, transcribes it as it goes, and
when a word from your list shows up it replaces exactly that fragment with a soft
tone before it is ever emitted.

Everything runs locally on CPU. No API, no account, no network.

<p align="center">
  <img src="docs/ventana.png" alt="Main window" width="49%">
  <img src="docs/asistente.png" alt="Setup guide" width="49%">
</p>

---

## Download

**[⬇ Download the installer](../../releases/latest)** — run it and you are done.
No admin rights needed; it creates the shortcuts and an uninstaller.

You also need [VB-CABLE](https://vb-audio.com/Cable/), which is free. The app
detects whether it is installed and links to it.

On first launch a seven-step guide explains the whole setup with diagrams: what
VB-CABLE is, why the audio is delayed, what to change in OBS, and how to keep the
video in sync.

---

## How it works

Windows gives no way to insert a program between a microphone and another
application, so the audio takes a detour through a virtual cable:

```
microphone ──► BEEP STREAM ──► CABLE Input ══╗
                                             ║  VB-CABLE
               OBS ◄── CABLE Output ═════════╝
```

Inside, the signal splits into two paths that never block each other:

| Path | What it does |
|---|---|
| **Audio** | Writes every incoming block into a ring buffer and reads it back out 1500 ms later. That delay is the whole trick: it buys time to decide before the audio is committed. |
| **Recognition** | Takes a copy, downsamples 48 → 16 kHz and feeds it to Vosk, which returns each word with a start and end timestamp. Matches are scheduled as intervals; when the playback cursor reaches one, the buffer contents are replaced with the censor tone. |

Recognition runs on its own thread, so a slow transcription costs a missed word —
never a dropout in the broadcast.

### Why 1500 ms

Vosk needs up to **830 ms** to confirm a word, and the recogniser runs three
staggered **800 ms** windows (which detects more than four 600 ms ones while using
26% less CPU). 830 + 800 sets the floor; 1500 ms leaves around 670 ms of headroom.
The app warns before starting if you go below it.

### Not bleeping innocent words

A small speech model mishears constantly. Matching literally misses `"joer"` for
`"joder"`; matching loosely bleeps `"pescado"`. So matching is **phonetic** — a key
tuned for Spanish that collapses `b/v`, `y/ll`, `c/k/q`, silent `h` and `s/z/c` —
plus bounded edit distance, in three sensitivity levels. A second list holds
innocent words that collide phonetically and short-circuits them.

The asymmetry is deliberate: a false negative costs a channel, a false positive
costs an awkward beep.

---

## Tech stack

| | |
|---|---|
| **Language** | Python 3.11 |
| **Speech recognition** | [Vosk](https://alphacephei.com/vosk/) 0.3.45 — offline, CPU, per-word timestamps (Spanish model, 40 MB) |
| **Audio I/O** | [sounddevice](https://python-sounddevice.readthedocs.io/) (PortAudio / WASAPI) for microphone and output |
| **Desktop audio** | [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) — WASAPI loopback, which PortAudio does not expose |
| **DSP** | NumPy: ring buffer, anti-alias filter, decimation, mixing, tone synthesis |
| **Interface** | Tkinter plus a custom component kit (`widgets.py`), monochrome design tokens (`tema.py`), and a canvas-drawn logo and diagrams |
| **Typeface** | [Inter](https://rsms.me/inter/), bundled and registered per-process — nothing is installed on the system |
| **System tray** | Raw Win32 through `ctypes` — no extra dependency |
| **Windows glue** | `ctypes`: AppUserModelID, icons, DPI awareness, dark title bar |
| **Packaging** | PyInstaller (onedir) + [Inno Setup](https://jrsoftware.org/isinfo.php) 6 |
| **Assets** | Pillow, build-time only — icons, banner and screenshots are generated from code |

Four runtime dependencies. Everything else — GUI, WAV, JSON, threads, tray icon —
is the Python standard library, to keep the executable small.

---

## Features

- **Two independent censors.** The microphone, and desktop audio (game, voice
  chat, music) captured through WASAPI loopback — no routing and no added latency
  for you. Each has its own engine and thread: if one dies, the other keeps going.
- **Built-in word editor.** Both lists, with search, add, edit and remove. Applies
  instantly, even mid-broadcast. The file keeps its comments and categories, so
  editing it by hand still works.
- **Failure has to be loud.** A censor that silently stops is worse than none,
  because you believe you are protected. The app watches for a dead recognition
  thread, an audio stream that stopped without erroring, and a microphone that is
  open but muted. All three show up in red — the only colour in an otherwise
  monochrome interface.
- **Test mode.** Records 8 seconds and lets you compare before and after without
  broadcasting anything.
- **Performance mode.** Hides the window in the tray; recognition keeps running.
- **Six censor sounds**, light and dark themes, and everything configurable.

<p align="center">
  <img src="docs/palabras.png" alt="Word list editor" width="60%">
</p>

---

## From source

```bash
git clone https://github.com/airamfuentes/beepstream
cd beepstream
instalar.bat          # dependencies + Vosk Spanish model (~40 MB)
BeepStream.bat        # run
```

Requires Python 3.11 on Windows 10 or later.

**Build the installer:**

```bash
construir.bat                  # PyInstaller + Inno Setup -> publicar\
construir.bat sininstalador    # just the portable folder
```

**Tests** — the first four need no microphone and no model:

```bash
py -3.11 tests/test_matcher.py            # phonetic matching
py -3.11 tests/test_engine.py             # ring buffer, DSP, interval logic
py -3.11 tests/test_falsos_positivos.py   # audits the real word list
py -3.11 tests/test_interfaz.py           # palette, type scale, windows
py -3.11 tests/test_integracion.py        # audio -> Vosk -> detection -> tone
py -3.11 tests/test_audio.py              # opens real devices
py -3.11 tests/test_cable.py              # end-to-end through VB-CABLE
```

`test_interfaz.py` is worth a note: colours and font sizes are requested by name
(`"panel_alto"`, `"seccion"`), which Python cannot check — a typo is a `KeyError`
raised only when that widget is painted. The test walks the modules with `ast`,
validates every role literal, then builds all the windows in both themes.

### Layout

```
main.py            entry point, CLI flags, console mode
├── gui.py         main window
│   ├── widgets.py themed component kit (cards, buttons, meters, toggles)
│   ├── tema.py    design tokens: monochrome palette, type scale, spacing
│   ├── marca.py   logo geometry, shared by the UI and the icon generator
│   ├── fuentes.py loads the bundled Inter privately
│   ├── sistema.py Win32 glue: app identity, icons, DPI, dark title bar
│   ├── asistente.py   first-run guided setup, canvas diagrams
│   ├── palabras.py    word-list editor
│   └── listas.py      comment-preserving read/write of the list files
├── engine.py      ring buffer, censor core, microphone engine
├── escritorio.py  second engine: desktop audio via WASAPI loopback
├── recognizer.py  Vosk wrapper, decimation, gain staging
├── matcher.py     phonetic matching and the safe-word list
├── beeper.py      censor tone synthesis (6 styles) and WAV handling
├── dispositivos.py  device resolution across MME/DirectSound/WASAPI
├── bandeja.py     system tray through raw Win32
├── config.py      config.json with defaults and forward migration
└── rutas.py       path resolution for source vs. frozen executable
```

---

## Privacy

Recognition is fully offline and works with no network connection. Nothing is
recorded, uploaded or transmitted. The only files written are `config.json` and,
if you use test mode, two `.wav` files you can delete.

---

## Licence

[MIT](LICENSE). Bundles [Inter](https://rsms.me/inter/) under the SIL Open Font
License. Speech recognition by [Vosk](https://alphacephei.com/vosk/) (Apache 2.0).
VB-CABLE is a separate free download from [VB-Audio](https://vb-audio.com/Cable/)
and is not redistributed here.
