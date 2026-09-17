<p align="center">
  <img src="docs/banner.png" alt="BEEP STREAM" width="100%">
</p>

<p align="center">
  <strong>Real-time profanity censor for live streams.</strong><br>
  Offline speech recognition, sub-second detection, no audio ever leaves the machine.
</p>

<p align="center">
  <a href="#how-it-works">How it works</a> ·
  <a href="#install">Install</a> ·
  <a href="#the-engineering-problem">The engineering problem</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="README.es.md">Español</a>
</p>

---

A live streamer who swears on air can lose a channel. Post-production bleeps do
not exist when the broadcast *is* the product. BEEP STREAM sits between the
microphone and the streaming software, listens to every word, and covers the
ones on a user-defined list with a soft tone — before they reach the audience.

Everything runs locally on CPU. No API, no account, no network.

<p align="center">
  <img src="docs/ventana.png" alt="Main window" width="49%">
  <img src="docs/asistente.png" alt="Setup guide" width="49%">
</p>

---

## How it works

Windows gives no way to insert a process between a microphone and an
application, so the audio takes a detour through a virtual cable:

```
microphone ──► BEEP STREAM ──► CABLE Input ══╗
                                             ║  VB-CABLE
               OBS ◄── CABLE Output ═════════╝
```

Inside, the signal is split in two:

- The **audio path** writes every incoming block into a ring buffer and reads it
  back out `N` milliseconds later. That delay is the whole trick: it buys time
  to decide before the audio is committed.
- The **recognition path** takes a copy of the same audio, downsamples it to
  16 kHz and feeds it to [Vosk](https://alphacephei.com/vosk/), which returns
  each recognised word with a start and end timestamp. Matches against the word
  list are scheduled as intervals; when the playback cursor reaches one, the
  buffer contents are replaced with the censor tone.

The two paths never block each other. Recognition runs on its own thread and
communicates through a lock-free interval list, so a slow transcription degrades
into a missed word — never into a dropout in the broadcast.

---

## Guided setup

Three things about this setup are not guessable: that it needs a virtual audio
cable, that the output is delayed by over a second, and that the same delay has
to be repeated on the video or the mouth no longer matches the voice. A wall of
text explains that badly, so the first run walks through seven steps, each with
a diagram drawn on a canvas, and checks what it can in real time.

<p align="center">
  <img src="docs/guia-retardo.png" alt="Why the audio is delayed" width="49%">
  <img src="docs/guia-cable.png" alt="Installing VB-CABLE" width="49%">
</p>

The delay step redraws itself from the configured value, the VB-CABLE step
detects whether the cable is installed and re-checks on demand, and the device
step opens the microphone live so the level meter moves while you talk.

---

## The engineering problem

### Why the delay is 1250 ms and not 630 ms

The obvious calculation says the delay only needs to cover recognition latency.
Measured on this model, the worst case from *end of spoken word* to *Vosk emits
the result* is **830 ms**. So 900 ms should be plenty.

It is not, and the reason is where the timestamps come from. Vosk reports word
boundaries relative to the **start of the utterance**, and it only finalises a
result when it detects a pause. A word spoken at the beginning of a long
sentence is not reported until the sentence ends. The delay has to cover
recognition latency *plus* the gap between the word and the pause that flushes
it.

`herramientas/medir_latencia.py` measures this on a real recording and prints
the distribution, so the number is calibrated rather than guessed. The window
warns when the configured delay drops below the measured safe threshold.

### Fuzzy matching without false positives

Speech recognition on a small model mishears constantly. Matching literally
misses `"joer"` for `"joder"`; matching loosely bleeps `"pescado"` because it
sounds like something else.

`matcher.py` uses a phonetic key tuned for Spanish (collapsing `b/v`, `y/ll`,
`c/k/q`, silent `h`, `s/z/c` seseo) plus bounded edit distance, with three
sensitivity levels. A second list, `palabras_seguras.txt`, holds innocent words
that collide phonetically with a censored one and short-circuits them.

The asymmetry is deliberate: a false negative costs a channel, a false positive
costs an awkward beep. The default leans toward beeping.

### Two independent censors

Desktop audio — game, voice chat, music, alerts — is captured through WASAPI
loopback rather than routed, so the user hears everything in real time with zero
added latency while the program works on a copy.

It runs as a **separate engine with its own recognizer and its own thread**. If
loopback capture dies mid-stream, the microphone censor keeps running: the
channel-ending risk is on the microphone, and one channel must not take the
other down with it.

### Failure has to be loud

A censor that silently stops is worse than no censor, because the streamer
believes they are protected. The window watches for three distinct failures:

| Failure | How it is detected |
|---|---|
| Recognition thread died | engine exposes a `fallo` flag |
| Audio stream stopped without erroring | sample counter stops advancing for 4 s |
| Microphone open but muted | peak level stays below −66 dBFS for 6 s |

All three surface as red text in the header, the only colour in an otherwise
monochrome interface.

---

## Install

### For users

Download the installer from [Releases](../../releases) and run it. No admin
rights required; it creates the shortcuts and an uninstaller. On first launch a
guided setup explains VB-CABLE, the delay, and the OBS configuration with
diagrams.

You will also need [VB-CABLE](https://vb-audio.com/Cable/) (free) — the setup
guide detects whether it is present and links to it.

### From source

```bash
git clone https://github.com/airamfuentes/beep-stream
cd beep-stream
instalar.bat          # dependencies + Vosk Spanish model (~40 MB)
BeepStream.bat        # run
```

Requires Python 3.11 on Windows 10 or later.

### Building the installer

```bash
construir.bat                  # PyInstaller + Inno Setup → publicar\
construir.bat sininstalador    # just the portable folder
```

Inno Setup is installed automatically via winget if missing.

---

## Architecture

```
main.py            entry point, CLI flags, console mode
├── gui.py         main window
│   ├── widgets.py themed component kit (cards, buttons, meters, toggles)
│   ├── tema.py    design tokens: monochrome palette, type scale, spacing
│   ├── marca.py   logo geometry, shared by the UI and the icon generator
│   ├── fuentes.py loads the bundled Inter privately, no system install
│   └── asistente.py   first-run guided setup, canvas diagrams
├── engine.py      ring buffer, censor core, microphone engine
├── escritorio.py  second engine: desktop audio via WASAPI loopback
├── recognizer.py  Vosk wrapper, decimation, gain staging
├── matcher.py     phonetic matching and the safe-word list
├── beeper.py      censor tone synthesis (6 styles) and WAV handling
├── dispositivos.py  device resolution across MME/DirectSound/WASAPI
├── bandeja.py     system tray via raw Win32, no extra dependency
├── config.py      config.json with defaults and forward migration
└── rutas.py       path resolution for source vs. frozen executable
```

### Choices worth explaining

**Tkinter, not Qt.** Ships with Python, adds nothing to the executable, and the
whole interface is a settings panel plus two meters. The cost is that Tkinter
has no component system and no theming — so `widgets.py` provides both, and
every widget registers which palette role each of its colours plays. Switching
themes is a dictionary swap and a repaint.

**Canvas-drawn logo and diagrams.** No PNG assets for the UI. The mark is
geometry in `marca.py`, rendered by Pillow for the `.ico` files and by a Tk
canvas in the window itself. One definition, correct in both themes, sharp at
any display scaling.

**Win32 tray via ctypes.** `pystray` would pull in Pillow, several megabytes in
the executable for one small feature. `bandeja.py` talks to `Shell_NotifyIcon`
directly, with a hidden window and its own message loop on a separate thread.

**`gc.freeze()` after startup.** Everything alive once the window is built —
modules, widgets, the word list — will live until exit and is never garbage.
Freezing it stops the collector from walking it on every full pass. Measured
with the model loaded, that pass cost 3.8–5.4 ms; audio blocks are 30 ms.

**Only one accent colour.** The interface is greyscale except for red, which is
reserved for "you are broadcasting unfiltered". When a censor has one alarm that
genuinely matters, decorative colour elsewhere is what buries it.

---

## Tests

```bash
py -3.11 tests/test_matcher.py            # phonetic matching, no hardware
py -3.11 tests/test_engine.py             # ring buffer, DSP, interval logic
py -3.11 tests/test_falsos_positivos.py   # audits the real word list
py -3.11 tests/test_integracion.py        # audio → Vosk → detection → tone
py -3.11 tests/test_audio.py              # opens real devices
py -3.11 tests/test_cable.py              # end-to-end through VB-CABLE
```

The first three need no microphone and no model.

---

## Privacy

Recognition is fully offline and works with no network connection. Nothing is
recorded, uploaded or transmitted. The only files written are `config.json` and,
if the test mode is used, two `.wav` files the user can delete.

---

## Licence

[MIT](LICENSE).

Bundles [Inter](https://rsms.me/inter/) under the SIL Open Font License.
Speech recognition by [Vosk](https://alphacephei.com/vosk/) (Apache 2.0).
VB-CABLE is a separate free download from [VB-Audio](https://vb-audio.com/Cable/)
and is not redistributed here.
