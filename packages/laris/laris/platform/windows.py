"""Windows backend: whisper.cpp STT + clipboard/Ctrl+V paste. The orb is
hosted by the Tauri tray (a transparent window), so the overlay here is a
no-op; per-app output ducking is out of scope, so the ducker is a no-op too.
Heavy imports are lazy (constructed only when this backend is)."""
from __future__ import annotations

import threading

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
        self._stt = None
        self._stt_lock = threading.Lock()
        self._status_sink = None

    def set_status_sink(self, sink) -> None:
        """Where to publish boot progress ("baixando modelo 43%"). Injected by
        daemon.run rather than taken in __init__, matching how the orb state is
        handed to make_overlay - the backend is built before the caller has
        decided who listens. Must be set before the transcriber is built."""
        self._status_sink = sink

    def _transcriber(self):
        """Built on first use, not in __init__.

        Constructing it probes the GPU, may download a model and starts a
        server - seconds of work. The daemon needs the overlay, the ducker and
        the hotkey long before any of that, and building eagerly here left the
        PTT key dead for the whole boot. warm() is what normally triggers this,
        from a background thread; a keypress that beats it just waits on the
        lock, so the audio is still recorded rather than lost."""
        with self._stt_lock:
            if self._stt is None:
                from laris.stt_whispercpp import WhisperCppTranscriber
                # Dictation only needs text, so the fast Parakeet fallback is
                # allowed when there is no GPU. Miris opts out of it - see
                # miris/pipeline.py.
                self._stt = WhisperCppTranscriber(allow_parakeet=True,
                                                  on_status=self._status_sink)
            return self._stt

    def stt_usable(self) -> bool:
        """False when every backend in the chain failed. daemon.run consults
        this before telling the tray dictation is ready - reporting ready while
        transcription returns "" forever is worse than reporting nothing."""
        stt = self._transcriber()
        return getattr(stt, "backend", "unavailable") != "unavailable"

    def warm(self) -> None:
        self._transcriber().warm()

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        return self._transcriber().transcribe(audio, sample_rate)

    def type_text(self, text: str) -> None:
        from laris.dictation_windows import type_text
        type_text(text)

    def make_overlay(self, url: str, state=None):
        return _StateOverlay(url, state=state)

    def make_ducker(self):
        return _NoOpDucker()
