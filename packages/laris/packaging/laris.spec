# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir spec for the torch-free laris dictation engine.
# Build from packages/laris/:  pyinstaller packaging/laris.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path

datas, binaries, hiddenimports = [], [], []
datas.append((str(Path(SPECPATH).parent / "frontend"), "frontend"))

# Native-heavy runtime deps: bundle everything they ship (submodules + data + DLLs).
for pkg in ("faster_whisper", "ctranslate2", "av", "onnxruntime", "sounddevice"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# uvicorn resolves its protocol/loop implementations by string at runtime.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += ["tokenizers", "huggingface_hub"]

a = Analysis(
    ["entry.py"],
    pathex=[".."],  # so `import laris` resolves against packages/laris/
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=[
        # keep the bundle lean and portable: never drag torch/mlx/pyobjc in
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
    name="laris-engine",
    console=False,  # no console window on Windows
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="laris-engine",
)
