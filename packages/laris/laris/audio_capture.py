"""Microphone capture for push-to-talk and hands-free.

Noise reduction used to live here as DeepFilterNet3. It needed torch, which
this bundle excludes, so on Windows it was always a passthrough that warned
once per utterance - a setting that could not do anything. It is gone, along
with the torch VAD it sat beside; voice activity detection now runs through
ONNX (see laris/vad_onnx.py).
"""
import queue
import threading
import time
from typing import Callable, Generator, Tuple

import numpy as np

from laris import config

_Utterance = Tuple[np.ndarray, int]  # (float32 mono, sample_rate)


def _open_stream(callback):
    """One mic stream shape for both capture paths. blocksize is the Silero
    window at 16 kHz, so the VAD gets exactly the frames it expects and no
    rebuffering is needed."""
    import sounddevice as sd

    return sd.InputStream(
        samplerate=config.SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=config.CHUNK_SAMPLES,
        callback=callback,
    )


def record_while(
    pressed: threading.Event,
    timeout_s: float | None = None,
    on_chunk: Callable[[np.ndarray], None] | None = None,
) -> np.ndarray:
    """Record from the microphone while pressed is set. Returns float32 mono
    audio. on_chunk sees each captured chunk live (desktop orb amplitude)."""
    timeout_s = timeout_s or config.MAX_SPEECH_DURATION_S
    chunks: list[np.ndarray] = []
    q: queue.Queue[np.ndarray] = queue.Queue()

    def _cb(indata, frames, time_info, status):
        q.put(indata[:, 0].copy())

    def _take(chunk: np.ndarray) -> None:
        chunks.append(chunk)
        if on_chunk is not None:
            on_chunk(chunk)

    start = time.monotonic()
    with _open_stream(_cb):
        while pressed.is_set() and (time.monotonic() - start) < timeout_s:
            try:
                _take(q.get(timeout=0.1))
            except queue.Empty:
                pass
        while not q.empty():
            _take(q.get_nowait())

    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)


class VadCapture:
    """Iterates voiced utterances, always-on. Thin name kept over the ONNX
    implementation because daemon.run imports it by this name."""

    def __init__(self) -> None:
        from laris.vad_onnx import OnnxVadCapture

        self._impl = OnnxVadCapture()

    def stream_utterances(
        self,
        should_stop: Callable[[], bool] | None = None,
        on_chunk: Callable[[np.ndarray], None] | None = None,
    ) -> Generator[_Utterance, None, None]:
        yield from self._impl.stream_utterances(
            should_stop=should_stop, on_chunk=on_chunk
        )
