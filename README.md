<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/voxis-wordmark-dark.svg">
    <img src="brand/voxis-wordmark-light.svg" alt="VOXIS" width="360">
  </picture>
</p>

<p align="center">
  Windows port of <a href="https://github.com/sammyjdev/voxis">sammyjdev/voxis</a>.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%20x64-0078D6" alt="Platform: Windows x64">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT"></a>
</p>

---

VOXIS turns your voice into text on your own machine. Hold a key and talk, and
the words land in whatever app is focused. Record a call, and you get a
transcript split by speaker, a summary, action items and a note filed in your
Obsidian vault. Speech recognition runs locally on your GPU (or CPU); no audio
is sent to a cloud service.

## About this port

[sammyjdev/voxis](https://github.com/sammyjdev/voxis) is a macOS-native app
built on Apple Silicon (`mlx-whisper`, Core Audio). This repository carries the
same product to Windows. It shares the upstream history, but the two projects
have since diverged on purpose: upstream dropped Windows support, and this fork
replaces every macOS-only piece with a Windows one.

| Concern | Upstream (macOS) | This port (Windows) |
|---|---|---|
| Speech-to-text | `mlx-whisper` on Metal | `whisper.cpp` on Vulkan, Parakeet fallback on CPU |
| Voice activity detection | Silero VAD on PyTorch | Same Silero model on ONNX Runtime |
| System audio (meetings) | Core Audio process tap | WASAPI loopback |
| Text output | Clipboard + Cmd+V | Clipboard + Ctrl+V |
| Default dictation key | Right-Cmd | Right-Shift |
| Distribution | Python venvs from source | One installer, engines frozen with PyInstaller |

## Family

| Package | What |
|---------|------|
| `packages/laris` | Dictation engine - push-to-talk / hands-free local STT, desktop orb overlay, themeable (`/theme` API). |
| `packages/miris` | Meeting engine - records mic + system audio (WASAPI loopback), transcribes locally, LLM summary + classification into the Obsidian vault. |
| `apps/tray` | Tray app (Tauri v2) - record meetings, dictation toggles, orb theme, native settings window. |
| `brand/` | Wordmark, mark and menu-bar variants (SVG). |

Each package keeps its own venv, tests and README - see inside.

## Features

- **Push-to-talk dictation.** Hold the key (Right-Shift by default), speak,
  release. The text is pasted into the focused app, with the first letter
  capitalized and a closing period added. Your previous clipboard is restored
  afterwards.
- **Hands-free dictation.** Double-tap the key and VOXIS keeps listening,
  typing each sentence as you finish it. Tap once to stop. Turned on from the
  tray's **Hands-free** toggle; the app never starts listening on its own at
  boot.
- **Meeting recording.** One click in the tray records your microphone and
  everything the PC plays (Zoom, Teams, Meet, Discord, any app). When you stop,
  VOXIS transcribes both sides and writes a meeting note.
- **Two-channel speaker separation.** Your mic is labelled "Eu" and system
  audio "Eles", so the transcript knows who spoke without a diarization model.
- **Notes routed to your vault.** An LLM picks a category, title, summary and
  action items; the note lands in the vault folder you mapped to that
  category.
- **The orb.** A floating, themeable waveform that reacts to your voice while
  VOXIS listens: 3 archetypes x 4 palettes, adjustable size and position.
- **Any modern GPU.** NVIDIA, AMD and Intel, integrated graphics included,
  with no CUDA or extra runtime to install.

## How transcription works

### Dictation (LARIS)

```
key held ─► mic @ 16 kHz ─► whisper.cpp (Vulkan GPU) ─► text ─► clipboard + Ctrl+V
                │
double-tap ─► Silero VAD cuts speech into sentences ─► (same path, per sentence)
```

1. **Capture.** The engine records mono audio at 16 kHz while the key is held.
   Clips shorter than half a second are ignored as accidental taps, and a
   single recording stops at 30 s.
2. **Segmenting (hands-free only).** The Silero VAD model scores every 32 ms
   chunk. Speech starts above a 0.5 probability and ends only after 400 ms
   below 0.35. The gap between the two thresholds keeps one sentence from
   being chopped into several.
3. **Recognition.** The audio goes to a resident `whisper-server` process that
   keeps the model loaded in GPU memory, so a warm request comes back in under
   a second.
4. **Output.** The text is pasted into the focused window.

Dictation is set to Portuguese (`pt`) by default. Change it with the
`STT_LANGUAGE` environment variable; an empty value lets Whisper detect the
language per utterance.

### Meetings (MIRIS)

1. **Record.** Two WAV files are written side by side: `mic.wav` (your
   microphone) and `system.wav` (WASAPI loopback of the default speaker), both
   16 kHz mono.
2. **Transcribe.** On stop, each channel goes through Whisper with segment
   timestamps and automatic language detection, so bilingual meetings work.
   Runs of repeated words (a known Whisper failure on noisy audio) are
   collapsed.
3. **Merge.** Segments from both channels are sorted into one timeline:
   `[03:12] Eles: ...`.
4. **Summarize.** The transcript is sent to the LLM CLI you configure, which
   returns category, title, summary and action items as JSON.
5. **Save.** A Markdown note with YAML frontmatter, summary, action-item
   checkboxes and the full transcript is written to the vault. If the LLM call
   fails, a transcript-only note goes to the inbox folder instead, so nothing
   is lost.

Use a headset for meetings. Without one, your mic also picks up the speakers
and "Eu" echoes what "Eles" said.

### Models

| Model | Used for | Size | Where it comes from |
|---|---|---|---|
| [Whisper large-v3-turbo](https://huggingface.co/ggerganov/whisper.cpp) (`ggml`, q5_0) | Dictation and meetings, default | 547 MB | Downloaded on first use |
| [Parakeet TDT 0.6B v3](https://huggingface.co/ggml-org/parakeet-GGUF) (`ggml`, q4_k) | Dictation only, when there is no GPU | 396 MB | Downloaded on first use, only on machines that need it |
| [Silero VAD](https://github.com/snakers4/silero-vad) (ONNX) | Hands-free sentence detection | 2.2 MB | Bundled in the installer |

**Why these.** `large-v3-turbo` keeps the accuracy of large-v3 with a 4-layer
decoder that decodes about 8x faster. The q5_0 quantization matched the
unquantized output word for word on Portuguese test samples. It is the same
model family the macOS version runs.

**Backend selection** happens at startup, best option first:

1. **Whisper on a Vulkan GPU.** VOXIS reads the list of GPUs and prefers a
   discrete card over integrated graphics, so a laptop uses its fast GPU
   instead of the default device.
2. **Parakeet on CPU.** If no GPU is available, dictation switches to Parakeet,
   which runs about 7x faster than Whisper on a CPU. It covers 25 European
   languages (Portuguese and English included) instead of ~99 and punctuates
   less well, so it is never the default.
3. **Whisper on CPU.** Slow but accurate. Used for languages Parakeet does not
   cover, and always for meetings: they need segment timestamps, which only
   Whisper produces, and they are processed after the call, so speed matters
   less.

**First launch is slower.** The model download (547 MB) and GPU shader
compilation (about 25 s, once per driver and build) happen on the first run.
The tray menu shows progress ("baixando modelo 42% de 547 MB") while this
runs. Both are one-time costs; later launches skip them.

## Install

The tray installer bundles both engines - no Python or Rust needed. Download the
latest build from the
[Releases page](https://github.com/hallygtree/voxis-windows/releases):
`VOXIS_x.y.z_x64_en-US.msi` (MSI, recommended) or
`VOXIS_x.y.z_x64-setup.exe` (NSIS). Builds are unsigned, so SmartScreen shows a
one-time "unknown publisher" prompt - choose **More info -> Run anyway**.

After installing:

1. **Allow the microphone** under **Settings > Privacy & security >
   Microphone** (allow desktop apps).
2. **Dictate.** Hold Right-Shift, speak, release. The tray menu (in
   Portuguese) has **Ditado**, **Gravar reunião**, **Última nota**, **Tema do
   orb** and **Configurações...**.
3. **For meeting summaries**, install an LLM CLI and make sure it is on your
   `PATH`. The default is the [Antigravity CLI](https://antigravity.google)
   (`agy`), but any CLI that takes a prompt and prints text works.

Full per-component steps are in **[docs/INSTALL.md](docs/INSTALL.md)**.

## Configuration

| What | Where |
|---|---|
| Dictation key, hands-free, Whisper model file | Tray settings window (saved to `~/.config/voice-at/laris-settings.json`) |
| Orb theme | Tray menu, or `~/.config/voice-at/orb-theme.json` |
| Downloaded models | `~/.config/voice-at/models/` |
| Vault root, category -> folder map, LLM command | `~/.miris/config.toml` (created on first run) |
| Meeting recordings and transcripts | `~/.miris/sessions/<timestamp>/` |
| Dictation engine log | `~/.config/voice-at/laris-engine.log` |

To use a different Whisper model, drop a `ggml` file into the models folder and
set its name in the tray settings.

## Privacy & security

- **Local by default.** Audio, transcripts and notes stay on your machine.
  There are two outbound paths, and you control both:
  - the one-time model download from Hugging Face on first use;
  - the LLM CLI you configure for meeting summaries (`agy` by default), which
    receives the meeting transcript.
- Dictated audio is never written to disk. The only exception is the Parakeet
  fallback, which writes a temporary WAV and deletes it right away.
- Recordings, transcripts and the auth token stay under your local user profile.
- Dependencies are scanned continuously (cargo-audit + npm audit, see
  `.github/workflows/security-audit.yml`).
- Releases are unsigned - see INSTALL.md.

## Status

The port is at **alpha** (`v0.4.1`): end-to-end dictation (push-to-talk and
hands-free) and meeting transcription work; UI parity and general polish are in
progress. The tray disables menu items when the engines are absent or offline.

Known limits on Windows:

- No volume ducking while you dictate (macOS lowers system audio; here
  background audio stays at full volume).
- No noise reduction (DeepFilterNet needs PyTorch, which the Windows bundle
  leaves out to stay small).
- Dictation uses the same formatting everywhere; there is no per-app
  formatting yet.

## License

[MIT](LICENSE). Original work © 2026 Sammy Junior; the Windows port is
distributed under the same license.
