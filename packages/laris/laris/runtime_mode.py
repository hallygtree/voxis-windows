"""Live ASSISTANT_MODE, shared between the HTTP server and the voice loop.

`config.MODE` is resolved once at import time, so the only way to change it used
to be restarting the daemon - which is exactly what the tray did on every
hands-free toggle. The restart tore down the orb window, dropped the websocket
and reloaded the whisper model, and to a user that reads as the app crashing and
reopening. The mode is a single word; it does not need a new process.

Held behind a lock because the HTTP server writes it from a uvicorn worker
thread while the PTT loop reads it on its own thread.
"""

import threading

VALID_MODES = ("ptt", "always_on")


class ModeValidationError(ValueError):
    """Raised for a mode outside VALID_MODES, so callers can answer 422."""


class ModeState:
    def __init__(self, mode: str = "ptt"):
        self._lock = threading.Lock()
        self._mode = mode if mode in VALID_MODES else "ptt"

    @property
    def mode(self) -> str:
        with self._lock:
            return self._mode

    @property
    def hands_free_allowed(self) -> bool:
        """always_on permits the double-tap gesture; it never starts a session
        on its own (see daemon.run)."""
        return self.mode == "always_on"

    def set(self, mode: str) -> str:
        if mode not in VALID_MODES:
            raise ModeValidationError(
                f"mode must be one of {VALID_MODES}, got {mode!r}"
            )
        with self._lock:
            self._mode = mode
        return mode
