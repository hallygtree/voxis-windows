# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir spec for the torch-free miris recorder engine.
# Build from packages/miris/:  pyinstaller packaging/miris.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path
import sys

# Ensure miris and laris packages are importable at spec-time for collect_submodules.
sys.path.insert(0, str(Path(SPECPATH).parent))
sys.path.insert(0, str(Path(SPECPATH).parent.parent / "laris"))

datas, binaries, hiddenimports = [], [], []

# Native-heavy runtime deps: bundle everything they ship (submodules + data +
# DLLs). `soundcard` is in this list, not in a try/except: it is what
# miris.loopback_windows imports to capture system audio, so it is required,
# not a fallback. Swallowing a failure here produced an exe that started fine
# and then recorded silence into system.wav - the frozen build is windowed, so
# the ImportError would have gone nowhere. Missing deps must break the build,
# which is the only place they are still cheap to notice.
# (pyaudiowpatch was listed here as an alternative backend but nothing imports
# it; it is not a dependency and collecting it only bloated the bundle.)
# STT no longer appears here: faster_whisper/ctranslate2 were dropped with the
# CUDA-only backend, and av/onnxruntime/tokenizers/huggingface_hub came in only
# as their dependencies (WAVs are read with the stdlib `wave` module).
for pkg in ("sounddevice", "soundcard"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# whisper.cpp binaries, staged by CI. miris-engine is its own onedir bundle and
# resolves them through sys._MEIPASS, so it needs its own copy rather than
# reaching into the laris engine's directory - the two are installed side by
# side and a relative hop between them would break if either moves. The
# duplication is more than paid for by dropping ctranslate2/onnxruntime/av.
_whispercpp = Path(SPECPATH).parent / "whispercpp"
if _whispercpp.is_dir():
    datas.append((str(_whispercpp), "whispercpp"))
else:
    raise SystemExit(
        f"[miris.spec] {_whispercpp} is missing - the whisper.cpp build step "
        "must run before PyInstaller. Failing here rather than shipping an "
        "engine that records meetings it cannot transcribe."
    )

# Ensure miris and laris submodules are included in the bundle
hiddenimports += collect_submodules("miris")
hiddenimports += collect_submodules("laris")

a = Analysis(
    ["entry.py"],
    pathex=[str(Path(SPECPATH).parent)],  # so `import miris` resolves against packages/miris/
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
    name="miris-engine",
    console=False,  # no console window on Windows (tray app)
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="miris-engine",
)
