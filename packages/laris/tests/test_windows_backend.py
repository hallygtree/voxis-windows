"""WindowsBackend delegation and the no-op overlay/ducker."""
import numpy as np


def test_windows_backend_delegates(monkeypatch):
    calls = {}

    class FakeStt:
        def warm(self):
            calls["warm"] = True

        def transcribe(self, audio, sample_rate):
            calls["transcribe"] = (len(audio), sample_rate)
            return "texto"

    monkeypatch.setattr("laris.stt_faster.FasterWhisperTranscriber", lambda: FakeStt())
    monkeypatch.setattr("laris.dictation_windows.type_text",
                        lambda text: calls.__setitem__("typed", text))

    from laris.platform.windows import WindowsBackend
    backend = WindowsBackend()
    backend.warm()
    assert backend.transcribe(np.zeros(8, dtype=np.float32), 16000) == "texto"
    backend.type_text("oi")
    assert calls == {"warm": True, "transcribe": (8, 16000), "typed": "oi"}


def test_windows_overlay_and_ducker_are_noops():
    from laris.platform.windows import WindowsBackend
    backend = WindowsBackend.__new__(WindowsBackend)
    overlay = backend.make_overlay("http://127.0.0.1:8421/overlay")
    ducker = backend.make_ducker()
    overlay.show("dictate")
    overlay.hide()
    ducker.duck()
    ducker.restore()
