import time
from pathlib import Path

import pytest

from miris.systemtap import SystemTap

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


def test_lifecycle_start_alive_stop(tmp_path):
    out = tmp_path / "out.wav"
    tap = SystemTap(out, binary=_fake_binary(tmp_path))
    tap.start()
    time.sleep(0.3)
    assert tap.alive()
    tap.stop()
    assert not tap.alive()
    assert "done" in out.read_text()
