"""Recording process: mic -> mic.wav, WASAPI loopback -> system.wav.
Runs until SIGTERM/SIGINT; finalizes both WAVs on the way out.
Spawned detached by `miris start` as: python -m miris.recorder <session_dir>."""
import os
import queue
import signal
import sys
import threading
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from miris.config import STOP_SENTINEL
from miris.systemtap import Tap, default_tap_factory

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1600  # 100ms
SENTINEL_POLL_S = 0.2


class WavWriter:
    """Incremental 16-bit PCM mono WAV writer."""

    def __init__(self, path: Path, sample_rate: int = SAMPLE_RATE):
        self._wav = wave.open(str(path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)

    def write(self, chunk: np.ndarray) -> None:
        pcm = np.clip(chunk, -1.0, 1.0)
        self._wav.writeframes((pcm * 32767).astype(np.int16).tobytes())

    def close(self) -> None:
        self._wav.close()


def _default_open_stream(callback):
    import sounddevice as sd
    return sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                          blocksize=CHUNK_SAMPLES, callback=callback)


def record(session_dir: Path, stop: threading.Event,
           tap_factory: Callable[[Path], Tap] | None = None,
           open_stream: Callable | None = None) -> None:
    """Record both channels into session_dir until stop is set."""
    if tap_factory is None:
        tap_factory = default_tap_factory()
    tap = tap_factory(session_dir / "system.wav")
    tap.start()
    writer: WavWriter | None = None
    open_stream = open_stream or _default_open_stream
    q: queue.Queue[np.ndarray] = queue.Queue()

    def _cb(indata, frames, time_info, status):
        q.put(indata[:, 0].copy())

    try:
        writer = WavWriter(session_dir / "mic.wav")
        with open_stream(_cb):
            while not stop.is_set():
                try:
                    writer.write(q.get(timeout=0.2))
                except queue.Empty:
                    pass
        # stream closed above: no producer left, drain is race-free
        while not q.empty():
            writer.write(q.get_nowait())
    finally:
        try:
            if writer is not None:
                writer.close()
        finally:
            tap.stop()


def watch_stop_sentinel(session_dir: Path, stop: threading.Event,
                        poll_s: float = SENTINEL_POLL_S) -> None:
    """Set `stop` once `miris stop` drops the sentinel file into session_dir.

    This is the stop channel on Windows: there is no deliverable SIGTERM
    there, `os.kill(pid, SIGTERM)` is `TerminateProcess`, and a terminated
    process never runs the `finally` that closes mic.wav / system.wav. Polling
    a file lets the recorder shut itself down and finalize both WAVs.
    """
    while not stop.wait(poll_s):  # returns True as soon as stop is set elsewhere
        if (session_dir / STOP_SENTINEL).exists():
            stop.set()
            return


def main() -> None:
    os.umask(0o077)  # private meeting audio - not world-readable on shared machines
    session_dir = Path(sys.argv[1])
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    threading.Thread(target=watch_stop_sentinel, args=(session_dir, stop),
                     daemon=True).start()
    pid_file = session_dir / "recorder.pid"
    # written last: `miris start` waits on this file to declare the recorder
    # up, and `miris stop` waits on it disappearing to know it is down
    pid_file.write_text(str(os.getpid()))
    try:
        record(session_dir, stop)
    finally:
        pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
