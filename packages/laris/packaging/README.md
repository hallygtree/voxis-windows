# Windows engine packaging

Freeze the torch-free dictation engine into a self-contained folder that ships
inside the VOXIS tray installer. No system Python on the target machine.

## Build (on Windows, or any host for a native engine)

```
cd packages/laris
python -m venv .venv-build
.venv-build\Scripts\pip install -r requirements.txt pyinstaller
.venv-build\Scripts\pyinstaller packaging/laris.spec --noconfirm
```

Output: `dist/laris-engine/laris-engine.exe` plus its `_internal/` deps.

## Decisions

- Torch-free: speech recognition runs through the bundled whisper.cpp
  binaries, and the hands-free VAD is Silero over onnxruntime, so nothing
  needs torch. It stays in `excludes` anyway - a transitive dependency
  dragging it back would add gigabytes without failing anything.
- CPU int8 baseline: CTranslate2 CPU is bundled and guaranteed. CUDA is a
  manual upgrade (install the CUDA CTranslate2 runtime), not bundled in v1.
- The Whisper model (`small`, a few hundred MB) downloads from HuggingFace on
  first run - not bundled.
