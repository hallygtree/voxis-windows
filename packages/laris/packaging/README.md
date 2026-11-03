# Windows engine packaging

Freeze the torch-free dictation engine into a self-contained folder that ships
inside the VOXIS tray installer. No system Python on the target machine.

## Build (on Windows, or any host for a native engine)

```
cd packages/laris
python -m venv .venv-build
.venv-build\Scripts\pip install -r requirements-windows.txt pyinstaller
.venv-build\Scripts\pyinstaller packaging/laris.spec --noconfirm
```

Output: `dist/laris-engine/laris-engine.exe` plus its `_internal/` deps.

## Decisions

- Torch-free: the PTT path needs no torch. VAD (silero) is hands-free only
  (out of scope) and denoise (DeepFilterNet) degrades to passthrough, so
  torch/torchaudio/silero-vad/deepfilternet are excluded. Installer stays lean.
- CPU int8 baseline: CTranslate2 CPU is bundled and guaranteed. CUDA is a
  manual upgrade (install the CUDA CTranslate2 runtime), not bundled in v1.
- The Whisper model (`small`, a few hundred MB) downloads from HuggingFace on
  first run - not bundled.
