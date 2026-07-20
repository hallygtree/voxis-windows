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

# Native-heavy runtime deps: bundle everything they ship (submodules + data + DLLs).
for pkg in ("faster_whisper", "ctranslate2", "av", "onnxruntime", "sounddevice"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Loopback audio capture (Windows WASAPI via pyaudiowpatch or soundcard)
# These are pure-Python or CFFI-based, usually don't need binaries, but include them anyway
try:
    d, b, h = collect_all("pyaudiowpatch")
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass  # pyaudiowpatch may not be installed; soundcard is the fallback

try:
    d, b, h = collect_all("soundcard")
    datas += d
    binaries += b
    hiddenimports += h
except Exception:
    pass  # soundcard optional; both are fallbacks

# Ensure miris and laris submodules are included in the bundle
hiddenimports += collect_submodules("miris")
hiddenimports += collect_submodules("laris")
hiddenimports += ["tokenizers", "huggingface_hub"]

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
