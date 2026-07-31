# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir spec for the torch-free laris dictation engine.
# Build from packages/laris/:  pyinstaller packaging/laris.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path
import sys

# Ensure laris package is importable at spec-time for collect_submodules.
sys.path.insert(0, str(Path(SPECPATH).parent))

datas, binaries, hiddenimports = [], [], []
datas.append((str(Path(SPECPATH).parent / "frontend"), "frontend"))

# whisper.cpp binaries, staged here by CI (see .github/workflows/tray-build.yml).
# Shipped as `datas` rather than `binaries` on purpose: binaries go through
# PyInstaller's dependency scanner, which can hoist a DLL out of this folder,
# and whisper-server.exe resolves ggml-vulkan.dll next to itself. Copying the
# tree verbatim keeps that layout - the same reason `frontend` is a data entry.
# laris/whispercpp_runtime.py::binaries_dir() reads sys._MEIPASS/whispercpp.
_whispercpp = Path(SPECPATH).parent / "whispercpp"
if _whispercpp.is_dir():
    datas.append((str(_whispercpp), "whispercpp"))
else:
    raise SystemExit(
        f"[laris.spec] {_whispercpp} is missing - the whisper.cpp build step "
        "must run before PyInstaller. Failing here rather than shipping an "
        "engine that cannot transcribe (it is packaged windowed, so it would "
        "fail silently at runtime)."
    )

# Silero VAD, 2.2 MB, MIT. Hands-free needs voice activity detection and the
# silero-vad package would drag torch in, so the same weights run through
# onnxruntime instead. Small enough to ship rather than make the user wait on
# another download the first time they double-tap.
_assets = Path(SPECPATH).parent / "assets"
if (_assets / "silero_vad.onnx").is_file():
    datas.append((str(_assets), "assets"))
else:
    raise SystemExit(
        f"[laris.spec] {_assets / 'silero_vad.onnx'} is missing - the VAD fetch "
        "step must run before PyInstaller. Failing here rather than shipping an "
        "engine whose hands-free toggle does nothing (it is packaged windowed, "
        "so that would fail in silence)."
    )

# Native-heavy runtime deps: bundle everything they ship (submodules + data + DLLs).
# STT is not here: faster_whisper/ctranslate2 were dropped with the CUDA-only
# backend, and av/tokenizers/huggingface_hub came in only as their dependencies
# (audio is read with the stdlib `wave` module). onnxruntime is back, but for
# the VAD alone - miris does no streaming detection and does not collect it.
for pkg in ("sounddevice", "onnxruntime"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# uvicorn resolves its protocol/loop implementations by string at runtime.
hiddenimports += collect_submodules("uvicorn")
# Ensure laris and all its lazy-loaded submodules are included in the bundle.
hiddenimports += collect_submodules("laris")

a = Analysis(
    ["entry.py"],
    pathex=[str(Path(SPECPATH).parent)],  # so `import laris` resolves against packages/laris/
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=[
        # Nothing installs torch any more - the VAD runs on onnxruntime - but
        # a transitive dependency pulling it back in would add gigabytes to
        # the installer without anything failing, so it stays barred.
        "torch", "torchaudio", "silero_vad", "deepfilternet",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="laris-engine",
    console=False,  # no console window on Windows
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="laris-engine",
)
