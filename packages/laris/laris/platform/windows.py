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
    # Building the transcriber probes the GPU, may download a model and starts
    # a server: daemon.run warms it on a background thread so the hotkey is
    # live from the first second.
    warms_in_background = True

    def __init__(self, allow_parakeet: bool = True) -> None:
        # Dictation only needs text, so it takes the fast Parakeet fallback
        # when there is no GPU; miris opts out (see miris/pipeline.py).
        self._allow_parakeet = allow_parakeet
        self._stt = None
        self._stt_lock = threading.Lock()
        self._orb_state = None
        self._status_sink = None

    def attach_orb_state(self, orb_state) -> None:
        """The orb lives in a tray window that reads this state over
        /overlay/state, and boot progress ("baixando modelo 43%") is published
        to the same place. Handed over by daemon.run, because the backend is
        built before the caller has decided who listens; must happen before
        the transcriber is built and before make_overlay."""
        self._orb_state = orb_state
        self._status_sink = orb_state.set_status

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
                self._stt = WhisperCppTranscriber(allow_parakeet=self._allow_parakeet,
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

    def transcribe(self, audio: np.ndarray, sample_rate: int,
                   language: str | None = None) -> str:
        kwargs = {"language": language} if language else {}
        return self._transcriber().transcribe(audio, sample_rate, **kwargs)

    def type_text(self, text: str) -> None:
        from laris.dictation_windows import type_text
        type_text(text)

    def make_overlay(self, url: str):
        return _StateOverlay(url, state=self._orb_state)

    def make_ducker(self):
        return _NoOpDucker()
