<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../brand/voxis-wordmark-dark.svg">
    <img src="../brand/voxis-wordmark-light.svg" alt="VOXIS" width="360">
  </picture>
</p>

<p align="center">
  Local dictation and meeting notes for Windows 11.<br>
  A fork of <a href="https://github.com/sammyjdev/voxis">sammyjdev/voxis</a> that adds Windows as a third platform.
</p>

<p align="center">
  <a href="https://github.com/hallygtree/voxis-windows/actions/workflows/windows.yml"><img src="https://github.com/hallygtree/voxis-windows/actions/workflows/windows.yml/badge.svg?branch=master" alt="windows build"></a>
  <a href="../LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

---

VOXIS keeps speech recognition on your machine. **LARIS** types what you say
into the focused app. **MIRIS** records meetings, transcribes both sides and
writes a summary note into your Obsidian vault. The tray app controls both.

This fork follows upstream and adds Windows on top of it. The macOS and Linux
code is upstream's, unchanged; for those platforms use
[sammyjdev/voxis](https://github.com/sammyjdev/voxis).

## What it does on Windows

- **Dictation.** Hold **Right-Shift**, speak, release, and the text is pasted
  where your cursor is. With hands-free enabled in the tray, double-tap the
  key and VOXIS types each sentence as you finish it.
- **Meetings.** Records your microphone and the default speaker as two
  channels, so "you" and "them" are separated without speaker diarization.
- **Any GPU.** Speech runs on [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
  with Vulkan, so NVIDIA, AMD and Intel GPUs work, integrated graphics
  included, with no CUDA to install. Without a GPU, dictation switches to
  Parakeet on the CPU.
- **One installer.** The tray and both engines are bundled with no system
  Python, venv or source checkout needed.
- **Offline after setup.** The first run downloads the Whisper model (547 MB).
  After that, audio and transcripts never leave the PC.

## Install

1. Download `VOXIS_<version>_x64_en-US.msi` from
   [Releases](https://github.com/hallygtree/voxis-windows/releases) and run it.
   Builds are unsigned, so SmartScreen asks once: **More info > Run anyway**.
2. Allow desktop apps to use the microphone under **Settings > Privacy &
   security > Microphone**.
3. Hold Right-Shift and talk.

Meeting summaries also need an LLM CLI on your `PATH` (`agy` by default). Set
your vault in `~/.miris/config.toml`.

The full guide covers the first-run model download, GPU and CPU behaviour,
log files and uninstalling: [docs/INSTALL-windows.md](../docs/INSTALL-windows.md).

## Requirements

- Windows 11, x64.
- A microphone. A headset helps in meetings, because without one your mic
  also picks up the other side.
- About 1 GB of disk for the app and the speech model.
- Optional: a Vulkan-capable GPU (any current driver includes Vulkan).

## How it differs from upstream

| | Upstream (macOS) | This fork (Windows) |
|---|---|---|
| Speech-to-text | `mlx-whisper` on Apple Silicon | whisper.cpp + Vulkan, Parakeet on CPU |
| Voice detection | Silero on PyTorch | Silero on ONNX Runtime |
| System audio | Swift CoreAudio helper | WASAPI loopback |
| Dictation key | `cmd_r` | Right-Shift |
| Packaging | source + venv | engines frozen with PyInstaller, MSI/NSIS installer |

## Status

> [!WARNING]
> Pre-release. The Windows port was rebuilt on top of current upstream, and
> CI builds and tests it on every change. A full install-and-use pass of this
> build on real hardware has not been done yet. Report problems with the log
> files listed in the install guide.

## Contributing

The fork stays mergeable with upstream by following three rules:

1. Never delete or rewrite upstream code.
2. Keep Windows code in Windows-only files (`*_windows.py`,
   `platform/windows.py`, `tauri.windows.conf.json`, `windows.yml`). Shared
   files only get small hooks.
3. Sync with `git merge upstream/master`, never rebase.

Local test commands and the sync routine are in the
[contributor section](../docs/INSTALL-windows.md#for-contributors-how-the-fork-stays-mergeable)
of the install guide.

## License

[MIT](../LICENSE). VOXIS is by [Sammy Junior](https://github.com/sammyjdev); the
Windows port is maintained in this fork.
