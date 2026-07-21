"""Orb state machine: thread-safe visibility/readiness/mode tracking with
change notification for long-poll endpoints.

This module intentionally avoids module-level globals - all state lives in
instances, which are injected into daemon.py and server.py. This allows
multiple daemon runs per process (tests) and keeps the factory pattern
intact. See server.py's docstring for why."""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class OrbState:
    """Immutable snapshot of the orb's state at a point in time."""
    visible: bool
    ready: bool
    mode: str | None
    serial: int


class OrbStateManager:
    """Thread-safe orb state with event-driven change notification.

    Serial starts at 1 (per SDD-C0 §18) so that since=0 always returns
    immediately. Increments only when the observable tuple (visible, ready,
    mode) actually changes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._visible = False
        self._ready = False
        self._mode: str | None = None
        self._serial = 1

    def snapshot(self) -> OrbState:
        """Return a consistent snapshot under lock."""
        with self._lock:
            return OrbState(
                visible=self._visible,
                ready=self._ready,
                mode=self._mode,
                serial=self._serial,
            )

    def show(self, mode: str) -> None:
        """Mark the orb visible with the given mode. Increments serial only
        if (visible, ready, mode) actually changes."""
        with self._lock:
            if not (self._visible and self._mode == mode):
                self._visible = True
                self._mode = mode
                self._serial += 1
                self._event.set()
                self._event.clear()

    def hide(self) -> None:
        """Mark the orb hidden. Increments serial only if state changes."""
        with self._lock:
            if self._visible or self._mode is not None:
                self._visible = False
                self._mode = None
                self._serial += 1
                self._event.set()
                self._event.clear()

    def set_ready(self, ready: bool) -> None:
        """Mark whether the backend is warmed and ready to transcribe."""
        with self._lock:
            if self._ready != ready:
                self._ready = ready
                self._serial += 1
                self._event.set()
                self._event.clear()

    def wait_for_change(self, since: int, timeout: float) -> OrbState:
        """Block until serial != since, or timeout expires. Returns the
        current state snapshot. This is blocking and must be called via
        asyncio.to_thread() in async contexts."""
        snapshot = self.snapshot()
        if snapshot.serial != since:
            return snapshot

        self._event.wait(timeout=timeout)
        return self.snapshot()
