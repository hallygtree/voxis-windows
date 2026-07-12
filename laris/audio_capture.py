"""Microphone capture for push-to-talk and always-on VAD."""
import queue
import threading
import time
from typing import Callable, Generator, Tuple

import numpy as np

from laris import config

_Utterance = Tuple[np.ndarray, int]  # (float32 mono, sample_rate)


def _open_stream(callback):
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
    """Iterates voiced utterances detected by Silero VAD, always-on."""

    def __init__(self) -> None:
        try:
            from silero_vad import load_silero_vad, VADIterator
        except ImportError:
            raise SystemExit(
                "[Audio] silero-vad not installed: pip install silero-vad"
            )
        self._model = load_silero_vad()
        self._VADIterator = VADIterator

    def stream_utterances(
        self,
        should_stop: Callable[[], bool] | None = None,
        on_chunk: Callable[[np.ndarray], None] | None = None,
    ) -> Generator[_Utterance, None, None]:
        import torch

        vad = self._VADIterator(
            self._model,
            threshold=config.VAD_THRESHOLD,
            sampling_rate=config.SAMPLE_RATE,
            min_silence_duration_ms=config.VAD_MIN_SILENCE_MS,
        )
        q: queue.Queue[np.ndarray] = queue.Queue()

        def _cb(indata, frames, time_info, status):
            q.put(indata[:, 0].copy())

        voiced: list[np.ndarray] = []
        in_speech = False
        max_chunks = int(
            config.MAX_SPEECH_DURATION_S * config.SAMPLE_RATE / config.CHUNK_SAMPLES
        )
        min_samples = int(config.MIN_SPEECH_DURATION_MS * config.SAMPLE_RATE / 1000)

        with _open_stream(_cb):
            while True:
                # polled even while silent: a blocking get() would make
                # hands-free impossible to stop until the next utterance
                if should_stop is not None and should_stop():
                    return
                try:
                    chunk = q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if on_chunk is not None:
                    on_chunk(chunk)
                event = vad(torch.from_numpy(chunk), return_seconds=False)

                if event and "start" in event:
                    in_speech = True
                    voiced = [chunk]
                    continue

                if in_speech:
                    voiced.append(chunk)
                    ended = (event and "end" in event) or len(voiced) >= max_chunks
                    if ended:
                        in_speech = False
                        audio = np.concatenate(voiced)
                        voiced = []
                        vad.reset_states()
                        if len(audio) >= min_samples:
                            yield audio, config.SAMPLE_RATE
