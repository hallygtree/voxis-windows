"""macOS backend: delegates to the existing mlx-whisper transcriber, the
CGEvent paste path, the AppKit overlay and the osascript ducker. Behavior
is identical to the pre-abstraction laris - this is a wrapper, not a change."""
from __future__ import annotations

import numpy as np


class MacOSBackend:
    def __init__(self) -> None:
        from laris.transcriber import Transcriber
        self._stt = Transcriber()

    def warm(self) -> None:
        self._stt.warm()

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        return self._stt.transcribe(audio, sample_rate)

    def type_text(self, text: str) -> None:
        from laris.dictation import type_text
        type_text(text)

    def make_overlay(self, url: str, state=None):
        from laris.overlay import Overlay
        return Overlay(url=url)

    def make_ducker(self):
        from laris.ducking import AudioDucker
        return AudioDucker()
