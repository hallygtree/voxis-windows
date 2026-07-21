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
for pkg in ("faster_whisper", "ctranslate2", "av", "onnxruntime", "sounddevice",
            "soundcard"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

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
