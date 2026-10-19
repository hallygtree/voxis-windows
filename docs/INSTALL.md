# Installing VOXIS

This repository is the **Windows** port of VOXIS. One installer ships the tray
plus both engines - dictation (`laris`) and meetings (`miris`) - frozen with
PyInstaller, so there is no system Python, venv or source clone involved. See
[Windows](#windows) below.

macOS (Apple Silicon) is maintained upstream at
[sammyjdev/voxis](https://github.com/sammyjdev/voxis). The from-source steps
kept in [macOS (from source)](#macos-from-source) describe that setup, and
upstream's own docs win where they differ.

---

## Windows

### 1. Install

Download `VOXIS_<version>_x64_en-US.msi` (recommended) or
`VOXIS_<version>_x64-setup.exe` from the
[Releases page](https://github.com/hallygtree/voxis-windows/releases) and run
it. The build is unsigned, so SmartScreen warns once - see
[Unsigned builds](#unsigned-builds).

### 2. Allow the microphone

Windows has no accessibility prompt like macOS. Enable the microphone under
**Settings > Privacy & security > Microphone**, including **Let desktop apps
access your microphone**.

### 3. Dictate

Hold the activation key (**Right-Shift** by default), speak, release - the text
is pasted into the focused app. Change the key in the tray's
**Configurações...** window.

For hands-free, check **Hands-free (duplo-toque na tecla)** in the tray menu
(or **Permitir hands-free** in settings), then double-tap the
key: VOXIS keeps listening and types each sentence as you finish it. Tap once
to stop.

### 4. Record meetings (optional)

Meeting notes need an LLM CLI on your `PATH` for the summary. The default is
the [Antigravity CLI](https://antigravity.google) (`agy`), logged in; any
prompt-in / text-out CLI works.

Then use **Gravar reunião** in the tray to start and **Parar gravação** to
stop. VOXIS records your mic and the default speaker (WASAPI loopback),
transcribes both, summarizes, and writes the note into your vault. **Última
nota** opens the most recent one.

Config is created on first run at `~/.miris/config.toml`: vault root,
category-to-folder map, and `llm_command`. Point `vault_root` at your Obsidian
vault before the first meeting. Raw recordings stay under
`~/.miris/sessions/<timestamp>/` until you delete them.

Tip: use a headset. Without one the mic also picks up the speakers, so your
channel echoes the other side.

### First run downloads the speech model

Speech recognition runs on [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
with the Vulkan backend. On first use the engine downloads Whisper
`large-v3-turbo` (q5_0, 547 MB) from Hugging Face into
`~/.config/voice-at/models/`, and compiles its GPU shaders (about 25 s, once per
driver and build). The tray menu shows progress while this happens. After that
it runs fully offline.

- **GPU.** Any Vulkan-capable GPU is used - NVIDIA, AMD or Intel, integrated
  graphics included. The Vulkan loader ships with the GPU driver; there is no
  CUDA or other runtime to install. A discrete card is preferred over
  integrated graphics.
- **No GPU.** Dictation falls back to Parakeet TDT v3 on the CPU (396 MB,
  downloaded only on machines that need it): much faster than Whisper on a CPU,
  but limited to 25 European languages. Meetings always use Whisper, on the CPU
  if necessary.
- **Other models.** Put another `ggml` Whisper file into the models folder and
  select it in the tray settings.

### If something breaks

The engines are windowed (no console), so they log to files. Send these when
reporting a problem:

- Dictation: `%USERPROFILE%\.config\voice-at\laris-engine.log` - startup
  output, the chosen GPU and model, and any crash traceback.
- Meetings: `recorder.log` inside the session folder under
  `%USERPROFILE%\.miris\sessions\`.

---

## Unsigned builds

VOXIS is **not code-signed** (that needs a paid developer certificate). The app
is safe; Windows just cannot verify the publisher. On first launch SmartScreen
shows "Windows protected your PC / unknown publisher" - click **More info >
Run anyway**.

---

## Uninstall / reset

- Uninstall **VOXIS** from **Settings > Apps > Installed apps**.
- State and config: `~/.config/voice-at/` (settings, orb theme, downloaded
  models, logs), `~/.miris/` (meeting config and recordings), and any notes
  already written into your vault.

---

## macOS (from source)

Inherited from upstream and not maintained in this fork. For current
instructions and macOS releases, use
[sammyjdev/voxis](https://github.com/sammyjdev/voxis).

### Prerequisites

- macOS 14.2 or newer (Core Audio process tap), Apple Silicon
- Python 3.11 (`python3.11 --version`)
- Xcode Command Line Tools for the audio helper: `xcode-select --install`
- Node.js 20+ and Rust stable if you want to build the tray from source
- An LLM CLI for meeting summaries (default `agy`, see above)

```bash
git clone https://github.com/sammyjdev/voxis.git ~/code/voxis
cd ~/code/voxis
```

### LARIS - dictation engine

```bash
cd ~/code/voxis/packages/laris
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m laris          # hold Right-Cmd to talk, double-tap for hands-free
```

First launch, macOS will prompt for **Accessibility** / **Input Monitoring**
(the global hotkey) and **Microphone**. Grant both.

### MIRIS - meeting recorder

MIRIS reuses LARIS for transcription, so install it into the MIRIS venv too.

```bash
cd ~/code/voxis/packages/miris
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r ../laris/requirements.txt
make -C helper                       # builds helper/audiotap (needs swiftc)
ln -sf "$PWD/.venv/bin/miris" ~/.local/bin/miris
miris doctor                         # triggers the System Audio Recording prompt
```

```bash
miris start     # begin recording (detached; survives closing the terminal)
miris status
miris stop      # stop, transcribe, summarize, save the note to your vault
```

### VOXIS Tray

```bash
cd ~/code/voxis/apps/tray
npm install
npm run tauri build        # bundle lands in src-tauri/target/release/bundle/
```

The tray reads the absolute paths of the engines from
`~/.config/voice-at/tray.json`; the defaults assume `~/code/voxis` and
`~/.local/bin/miris`, so adjust that file if you cloned elsewhere.

Gatekeeper blocks unsigned apps ("damaged" or "cannot be verified"). Clear the
quarantine flag once after moving VOXIS to Applications:

```bash
xattr -cr /Applications/VOXIS.app
```
