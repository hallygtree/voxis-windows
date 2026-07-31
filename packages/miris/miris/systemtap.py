"""System audio capture: the Tap interface and the factory that picks one.

Only the WASAPI loopback backend remains - the macOS audiotap subprocess went
with the rest of the macOS support. The interface stays because
loopback_windows implements it and the recorder is written against it, not
against a concrete class.
"""
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable


class Tap(ABC):
    """Abstract interface for system audio capture."""

    @abstractmethod
    def start(self) -> None:
        """Start capturing system audio."""

    @abstractmethod
    def alive(self) -> bool:
        """Check if capture is running."""

    @abstractmethod
    def stop(self, grace_s: float = 5.0) -> None:
        """Stop capturing and finalize output WAV."""


def default_tap_factory() -> Callable[[Path], Tap]:
    """The WASAPI loopback tap. Fails loudly elsewhere rather than returning
    something that records silence."""
    if sys.platform != "win32":
        raise SystemExit(
            f"[miris] this is a Windows-only port; {sys.platform} is not supported"
        )
    from miris.loopback_windows import WindowsLoopbackTap

    return WindowsLoopbackTap
