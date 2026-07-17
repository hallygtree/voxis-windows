"""Windows backend: faster-whisper STT + clipboard/Ctrl+V paste. The orb is
hosted by the Tauri tray (a transparent window), so the overlay here is a
no-op; per-app output ducking is out of scope, so the ducker is a no-op too.
Heavy imports are lazy (constructed only when this backend is)."""
from __future__ import annotations

import numpy as np


class _NoOpOverlay:
    """The orb is a Tauri window on Windows; the daemon still calls show/hide,
    so accept them and do nothing - the orb reacts to /ws/voice phase events."""
    def __init__(self, url: str) -> None:
        self.url = url

    def show(self, mode: str) -> None:
        pass

    def hide(self) -> None:
        pass


class _NoOpDucker:
    def duck(self) -> None:
        pass

    def restore(self) -> None:
        pass


class WindowsBackend:
    def __init__(self) -> None:
        from laris.stt_faster import FasterWhisperTranscriber
        self._stt = FasterWhisperTranscriber()

    def warm(self) -> None:
        self._stt.warm()

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        return self._stt.transcribe(audio, sample_rate)

    def type_text(self, text: str) -> None:
        from laris.dictation_windows import type_text
        type_text(text)

    def make_overlay(self, url: str):
        return _NoOpOverlay(url)

    def make_ducker(self):
        return _NoOpDucker()
