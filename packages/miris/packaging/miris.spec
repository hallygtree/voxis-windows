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
# miris.systemtap_windows imports to capture system audio, so it is required,
# not a fallback. Swallowing a failure here produced an exe that started fine
# and then recorded silence into system.wav - the frozen build is windowed, so
# the ImportError would have gone nowhere. Missing deps must break the build,
# which is the only place they are still cheap to notice.
# (pyaudiowpatch was listed here as an alternative backend but nothing imports
# it; it is not a dependency and collecting it only bloated the bundle.)
# onnxruntime runs Silero VAD to split each channel into utterances (the same
# model laris uses for hands-free); psutil reads process command lines, which
# is how the CLI recognises its own recorder where there is no `ps`.
for pkg in ("sounddevice", "soundcard", "onnxruntime", "psutil"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# whisper.cpp binaries, staged by CI. miris-engine is its own onedir bundle and
# resolves them through sys._MEIPASS, so it needs its own copy rather than
# reaching into the laris engine's directory - the two are installed side by
# side and a relative hop between them would break if either moves.
_whispercpp = Path(SPECPATH).parent / "whispercpp"
if _whispercpp.is_dir():
    datas.append((str(_whispercpp), "whispercpp"))
else:
    raise SystemExit(
        f"[miris.spec] {_whispercpp} is missing - the whisper.cpp build step "
        "must run before PyInstaller. Failing here rather than shipping an "
        "engine that records meetings it cannot transcribe."
    )

# Silero VAD model, the same file laris ships (fetched by CI into
# packages/laris/assets). laris.vad_onnx finds it under _MEIPASS/assets.
_assets = Path(SPECPATH).parent.parent / "laris" / "assets"
if (_assets / "silero_vad.onnx").is_file():
    datas.append((str(_assets), "assets"))
else:
    raise SystemExit(
        f"[miris.spec] {_assets / 'silero_vad.onnx'} is missing - the VAD fetch "
        "step must run before PyInstaller. Without it every meeting channel "
        "would fail to split into utterances, in a windowed process."
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
        # keep the bundle lean and portable: never drag torch/mlx/pyobjc/silero_vad in
        "torch", "torchaudio", "silero_vad", "df", "deepfilternet",
        "mlx", "mlx_whisper", "AppKit", "WebKit", "objc", "Foundation",
        "Quartz", "ApplicationServices",
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
