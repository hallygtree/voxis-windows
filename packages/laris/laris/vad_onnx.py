"""Streaming voice activity detection with Silero, over ONNX Runtime.

The `silero-vad` package pulls torch, which the Windows engine bundle excludes
on purpose - so hands-free simply did not exist there: `VadCapture.__init__`
raised SystemExit and the daemon fell back to push-to-talk forever. This is the
same model, same weights, driven through onnxruntime instead.

The model is stateful and expects exactly 512 samples per call at 16 kHz, which
is what `audio_capture._open_stream` already delivers (`config.CHUNK_SAMPLES`).
Its recurrent state has to be carried between calls and reset between
utterances, or probabilities drift.

Thresholding follows silero's own VADIterator: speech starts at `threshold` but
only ends below `threshold - 0.15`. That gap is deliberate - a single rule makes
the decision flap around the boundary, chopping one sentence into several.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np

from laris import config

# silero's VADIterator uses this offset between the start and end thresholds
_NEG_THRESHOLD_OFFSET = 0.15
_STATE_SHAPE = (2, 1, 128)
# Chunks of the closing silence kept after the last voiced one, so a trailing
# consonant is not clipped off the final word.
_TAIL_PAD_CHUNKS = 3


def model_path() -> Path:
    """The bundled model. 2.2 MB, MIT-licensed, shipped in the installer rather
    than downloaded: a file this small does not justify another wait on first
    use."""
    override = os.environ.get("VOXIS_VAD_MODEL")
    if override:
        return Path(override).expanduser()
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    return base / "assets" / "silero_vad.onnx"


class SileroOnnxVad:
    """One ONNX session plus the recurrent state it needs between chunks."""

    def __init__(self, session=None) -> None:
        if session is None:
            import onnxruntime  # lazy: only hands-free needs it

            options = onnxruntime.SessionOptions()
            # One thread: this runs 31 times a second on 512 samples. Letting
            # onnxruntime spin up a pool would cost more in scheduling than the
            # inference itself, and it competes with the transcription running
            # on the same machine.
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = 1
            session = onnxruntime.InferenceSession(
                str(model_path()), options, providers=["CPUExecutionProvider"]
            )
        self._session = session
        self._state = np.zeros(_STATE_SHAPE, dtype=np.float32)

    def reset(self) -> None:
        self._state = np.zeros(_STATE_SHAPE, dtype=np.float32)

    def probability(self, chunk: np.ndarray) -> float:
        """Speech probability for one 512-sample window."""
        out, state = self._session.run(
            None,
            {
                "input": chunk.reshape(1, -1).astype(np.float32),
                "state": self._state,
                "sr": np.array(config.SAMPLE_RATE, dtype=np.int64),
            },
        )
        self._state = state
        return float(np.asarray(out).reshape(-1)[0])


class OnnxVadCapture:
    """Drop-in for `audio_capture.VadCapture` on torch-free installs.

    Yields `(float32 audio, sample_rate)` per utterance, the contract
    `daemon._run_hands_free_session` consumes."""

    def __init__(self, vad=None) -> None:
        self._vad = vad if vad is not None else SileroOnnxVad()

    def stream_utterances(self, should_stop=None, on_chunk=None):
        import queue

        from laris.audio_capture import _open_stream

        chunk_ms = 1000.0 * config.CHUNK_SAMPLES / config.SAMPLE_RATE
        max_chunks = int(
            config.MAX_SPEECH_DURATION_S * config.SAMPLE_RATE / config.CHUNK_SAMPLES
        )
        min_samples = int(config.MIN_SPEECH_DURATION_MS * config.SAMPLE_RATE / 1000)
        start_at = config.VAD_THRESHOLD
        end_below = config.VAD_THRESHOLD - _NEG_THRESHOLD_OFFSET

        q: "queue.Queue[np.ndarray]" = queue.Queue()

        def _cb(indata, frames, time_info, status):
            q.put(indata[:, 0].copy())

        voiced: list[np.ndarray] = []
        in_speech = False
        silence_ms = 0.0
        last_voice = -1     # index in `voiced` of the last chunk with speech
        self._vad.reset()

        with _open_stream(_cb):
            while True:
                # Polled even in silence: a blocking get() would leave
                # hands-free impossible to stop until the next utterance.
                if should_stop is not None and should_stop():
                    return
                try:
                    chunk = q.get(timeout=0.1)
                except queue.Empty:
                    continue
                if on_chunk is not None:
                    on_chunk(chunk)

                probability = self._vad.probability(chunk)

                if not in_speech:
                    if probability >= start_at:
                        in_speech = True
                        silence_ms = 0.0
                        voiced = [chunk]
                        last_voice = 0
                    continue

                voiced.append(chunk)
                if probability < end_below:
                    silence_ms += chunk_ms
                else:
                    silence_ms = 0.0
                    last_voice = len(voiced) - 1

                if silence_ms >= config.VAD_MIN_SILENCE_MS or len(voiced) >= max_chunks:
                    # Measure and emit the speech, not the silence that closed
                    # it. Counting the closing gap made a 160ms cough pass a
                    # 400ms minimum - and in hands-free a spurious utterance is
                    # typed straight into whatever the user has focused.
                    keep = min(len(voiced), last_voice + 1 + _TAIL_PAD_CHUNKS)
                    audio = np.concatenate(voiced[:keep])
                    speech_samples = (last_voice + 1) * config.CHUNK_SAMPLES
                    in_speech, voiced, silence_ms, last_voice = False, [], 0.0, -1
                    self._vad.reset()
                    if speech_samples >= min_samples:
                        yield audio, config.SAMPLE_RATE
