"""Selects the platform backend at runtime. Import is lazy so importing
this package never pulls mlx (macOS) or ctranslate2 (windows) unless the
matching backend is actually constructed."""
from __future__ import annotations

import sys

from laris.platform.base import PlatformBackend


def get_backend() -> PlatformBackend:
    if sys.platform == "darwin":
        from laris.platform.macos import MacOSBackend
        return MacOSBackend()
    if sys.platform == "win32":
        from laris.platform.windows import WindowsBackend  # lands in Plan 2
        return WindowsBackend()
    raise SystemExit(f"[laris] unsupported platform: {sys.platform}")
