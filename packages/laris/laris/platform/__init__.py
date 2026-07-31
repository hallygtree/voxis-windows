"""The platform backend. Windows is the only one this port supports, so this
is a single constructor rather than a dispatch - but it stays behind a function
because the import is deliberately lazy: constructing the backend probes the
GPU and starts a server, and importing this package must not."""
from __future__ import annotations

import sys

from laris.platform.base import PlatformBackend


def get_backend() -> PlatformBackend:
    if sys.platform != "win32":
        raise SystemExit(
            f"[laris] this is a Windows-only port; {sys.platform} is not supported"
        )
    from laris.platform.windows import WindowsBackend
    return WindowsBackend()
