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

    monkeypatch.setattr("laris.stt_whispercpp.WhisperCppTranscriber",
                        lambda allow_parakeet=True: FakeStt())
    monkeypatch.setattr("laris.dictation_windows.type_text",
                        lambda text: calls.__setitem__("typed", text))

    from laris.platform.windows import WindowsBackend
    backend = WindowsBackend()
    backend.warm()
    assert backend.transcribe(np.zeros(8, dtype=np.float32), 16000) == "texto"
    backend.type_text("oi")
    assert calls == {"warm": True, "transcribe": (8, 16000), "typed": "oi"}


def test_windows_overlay_without_state_is_noop():
    """Overlay without injected state degrades to no-op."""
    from laris.platform.windows import WindowsBackend
    backend = WindowsBackend.__new__(WindowsBackend)
    overlay = backend.make_overlay("http://127.0.0.1:8421/overlay")
    # These should not raise even without state
    overlay.show("dictate")
    overlay.hide()


def test_windows_overlay_with_state_writes():
    """Overlay with injected state updates the state on show/hide."""
    from laris.orb_state import OrbStateManager
    from laris.platform.windows import WindowsBackend
    backend = WindowsBackend.__new__(WindowsBackend)
    state = OrbStateManager()
    overlay = backend.make_overlay("http://127.0.0.1:8421/overlay", state=state)

    assert state.snapshot().visible is False
    overlay.show("dictate")
    snapshot = state.snapshot()
    assert snapshot.visible is True
    assert snapshot.mode == "dictate"

    overlay.hide()
    snapshot = state.snapshot()
    assert snapshot.visible is False
    assert snapshot.mode is None


def test_windows_ducker_is_noop():
    from laris.platform.windows import WindowsBackend
    backend = WindowsBackend.__new__(WindowsBackend)
    ducker = backend.make_ducker()
    ducker.duck()
    ducker.restore()
