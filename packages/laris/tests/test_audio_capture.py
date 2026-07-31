"""Push-to-talk capture.

The VAD used to be tested here behind a torch skip marker, which meant it never
ran on the only platform this port supports. It lives in test_vad_onnx.py now
and runs everywhere. The DeepFilterNet tests went with the denoise code, which
could never work without torch.
"""
import threading
from contextlib import contextmanager

import numpy as np


def test_record_while_returns_empty_audio_when_event_is_clear(monkeypatch):
    from laris import audio_capture

    class FakeStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(audio_capture, "_open_stream", lambda _callback: FakeStream())

    audio = audio_capture.record_while(threading.Event())

    assert isinstance(audio, np.ndarray)
    assert audio.dtype == np.float32
    assert audio.size == 0


def test_record_while_reports_chunks_live(monkeypatch):
    """The desktop orb needs live amplitude while the key is held - each
    captured chunk must reach on_chunk before the recording ends."""
    from laris import audio_capture

    pressed = threading.Event()
    pressed.set()

    @contextmanager
    def fake_stream(callback):
        callback(np.full((4, 1), 0.5, dtype=np.float32), 4, None, None)
        yield

    monkeypatch.setattr(audio_capture, "_open_stream", fake_stream)

    seen = []

    def on_chunk(chunk):
        seen.append(chunk.copy())
        pressed.clear()  # stop after the first chunk

    audio = audio_capture.record_while(pressed, on_chunk=on_chunk)

    assert len(seen) == 1
    assert len(audio) == 4


def test_vad_capture_delegates_to_the_onnx_implementation(monkeypatch):
    """daemon.run imports VadCapture by name; the ONNX class is what it must
    actually get now that the torch path is gone."""
    from laris import audio_capture

    marker = object()

    class FakeOnnx:
        def stream_utterances(self, should_stop=None, on_chunk=None):
            yield marker, 16000

    monkeypatch.setattr("laris.vad_onnx.OnnxVadCapture", lambda: FakeOnnx())

    assert list(audio_capture.VadCapture().stream_utterances()) == [(marker, 16000)]
