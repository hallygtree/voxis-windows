"""Windows backend: whisper.cpp STT + clipboard/Ctrl+V paste. The orb is
hosted by the Tauri tray (a transparent window), so the overlay here is a
no-op; per-app output ducking is out of scope, so the ducker is a no-op too.
Heavy imports are lazy (constructed only when this backend is)."""
from __future__ import annotations

import numpy as np


class _StateOverlay:
    """The orb is a Tauri window on Windows; the daemon still calls show/hide,
    so these methods update the orb state so /overlay/state reflects current
    visibility. Degrades to no-op silently when state is None."""
    def __init__(self, url: str, state=None) -> None:
        self.url = url
        self.state = state

    def show(self, mode: str) -> None:
        if self.state is not None:
            self.state.show(mode)

    def hide(self) -> None:
        if self.state is not None:
            self.state.hide()


class _NoOpDucker:
    def duck(self) -> None:
        pass

    def restore(self) -> None:
        pass


class WindowsBackend:
    def __init__(self) -> None:
        from laris.stt_whispercpp import WhisperCppTranscriber
        # Dictation only needs text, so the fast Parakeet fallback is allowed
        # when there is no GPU. Miris opts out of it - see miris/pipeline.py.
        self._stt = WhisperCppTranscriber(allow_parakeet=True)

    def warm(self) -> None:
        self._stt.warm()

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        return self._stt.transcribe(audio, sample_rate)

    def type_text(self, text: str) -> None:
        from laris.dictation_windows import type_text
        type_text(text)

    def make_overlay(self, url: str, state=None):
        return _StateOverlay(url, state=state)

    def make_ducker(self):
        return _NoOpDucker()
