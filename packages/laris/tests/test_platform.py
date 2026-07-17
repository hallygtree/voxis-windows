"""Platform backend selection and the macOS backend's delegation."""
import sys

import numpy as np
import pytest

from laris import platform as laris_platform
from laris.platform.macos import MacOSBackend


def test_get_backend_darwin_returns_macos(monkeypatch):
    # mock Transcriber so constructing MacOSBackend does not load real
    # mlx_whisper - importing mlx after torch in the same process aborts the
    # interpreter (a fatal native crash), and no other test loads real mlx
    monkeypatch.setattr("laris.transcriber.Transcriber", lambda: object())
    monkeypatch.setattr(sys, "platform", "darwin")
    backend = laris_platform.get_backend()
    assert isinstance(backend, MacOSBackend)


def test_get_backend_unsupported_exits(monkeypatch):
    monkeypatch.setattr(sys, "platform", "sunos")
    with pytest.raises(SystemExit):
        laris_platform.get_backend()


def test_macos_backend_delegates(monkeypatch):
    calls = {}

    class FakeStt:
        def warm(self):
            calls["warm"] = True

        def transcribe(self, audio, sample_rate):
            calls["transcribe"] = (len(audio), sample_rate)
            return "hello"

    monkeypatch.setattr("laris.transcriber.Transcriber", lambda: FakeStt())
    monkeypatch.setattr("laris.dictation.type_text",
                        lambda text: calls.__setitem__("typed", text))

    backend = MacOSBackend()
    backend.warm()
    assert backend.transcribe(np.zeros(10, dtype=np.float32), 16000) == "hello"
    backend.type_text("hi there")
    assert calls == {"warm": True, "transcribe": (10, 16000), "typed": "hi there"}


def test_macos_backend_overlay_and_ducker_are_real_types():
    from laris.overlay import Overlay
    from laris.ducking import AudioDucker

    backend = MacOSBackend.__new__(MacOSBackend)  # no Transcriber construction
    assert isinstance(backend.make_overlay("http://x"), Overlay)
    assert isinstance(backend.make_ducker(), AudioDucker)
