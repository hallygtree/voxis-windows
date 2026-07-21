import sys
import time
from pathlib import Path

import pytest

from miris.systemtap import SystemTap

# SystemTap is the macOS backend (the audiotap Swift helper); Windows uses
# WindowsLoopbackTap instead (see test_loopback_windows.py). The fixture below
# is a /bin/sh script, which Windows cannot execute at all.
posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="SystemTap is the macOS/POSIX backend; Windows uses WindowsLoopbackTap",
)

FAKE_HELPER = """#!/bin/sh
trap 'echo done >> "$1"; exit 0' TERM INT
echo started > "$1"
while true; do sleep 0.1; done
"""


def _fake_binary(tmp_path) -> Path:
    binary = tmp_path / "fake_audiotap"
    binary.write_text(FAKE_HELPER)
    binary.chmod(0o755)
    return binary


def test_start_raises_when_binary_missing(tmp_path):
    tap = SystemTap(tmp_path / "out.wav", binary=tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        tap.start()


@posix_only
def test_lifecycle_start_alive_stop(tmp_path):
    out = tmp_path / "out.wav"
    tap = SystemTap(out, binary=_fake_binary(tmp_path))
    tap.start()
    # the fake helper writes the file only AFTER installing its TERM trap;
    # polling for it (instead of a fixed sleep) kills the SIGTERM race
    for _ in range(100):
        if out.exists():
            break
        time.sleep(0.05)
    assert out.exists()
    assert tap.alive()
    tap.stop()
    assert not tap.alive()
    assert "done" in out.read_text()
