"""Backend selection. There is one backend - this port is Windows-only - so
what is left to guard is that anything else fails loudly instead of importing
half a stack and dying somewhere less obvious. Delegation itself is covered by
test_windows_backend.py."""
import sys

import pytest

from laris import platform as laris_platform


def test_windows_gets_the_windows_backend(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("laris.stt_whispercpp.WhisperCppTranscriber",
                        lambda **_kwargs: object())
    from laris.platform.windows import WindowsBackend

    assert isinstance(laris_platform.get_backend(), WindowsBackend)


@pytest.mark.parametrize("platform", ["darwin", "linux", "sunos"])
def test_every_other_platform_exits_with_a_reason(monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    with pytest.raises(SystemExit) as excinfo:
        laris_platform.get_backend()
    assert "Windows-only" in str(excinfo.value)
