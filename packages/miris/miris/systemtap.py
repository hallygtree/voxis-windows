"""System audio capture: platform-specific backends (macOS audiotap, Windows WASAPI loopback)."""
import os
import signal
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

DEFAULT_BIN = Path(__file__).resolve().parent.parent / "helper" / "audiotap"


class Tap(ABC):
    """Abstract interface for system audio capture."""

    @abstractmethod
    def start(self) -> None:
        """Start capturing system audio."""
        pass

    @abstractmethod
    def alive(self) -> bool:
        """Check if capture is running."""
        pass

    @abstractmethod
    def stop(self, grace_s: float = 5.0) -> None:
        """Stop capturing and finalize output WAV."""
        pass


class SystemTap(Tap):
    """macOS system audio capture via audiotap subprocess."""

    def __init__(self, out_wav: Path, binary: Path | None = None):
        self.out_wav = out_wav
        # explicit binary wins; MIRIS_AUDIOTAP only overrides the default
        self.binary = Path(binary or os.environ.get("MIRIS_AUDIOTAP") or DEFAULT_BIN)
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        if not self.binary.exists():
            raise FileNotFoundError(
                f"audiotap binary not found: {self.binary} (run: make -C helper)"
            )
        self.proc = subprocess.Popen([str(self.binary), str(self.out_wav)])

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, grace_s: float = 5.0) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


def default_tap_factory() -> Callable[[Path], Tap]:
    """Return platform-specific Tap factory.

    On Windows: returns WindowsLoopbackTap (WASAPI loopback in-process)
    On macOS/Linux: returns SystemTap (audiotap subprocess)
    """
    if sys.platform == "win32":
        from miris.loopback_windows import WindowsLoopbackTap
        return WindowsLoopbackTap
    else:
        return SystemTap
