import threading

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


def test_stream_utterances_stops_when_asked(monkeypatch):
    """Hands-free relies on should_stop being polled even while the mic is
    silent - the generator must return instead of blocking forever."""
    from contextlib import contextmanager

    from laris import audio_capture

    @contextmanager
    def fake_stream(callback):
        yield

    monkeypatch.setattr(audio_capture, "_open_stream", fake_stream)

    vad = object.__new__(audio_capture.VadCapture)
    vad._model = object()
    vad._VADIterator = lambda model, **kwargs: lambda chunk, return_seconds: None

    utterances = list(vad.stream_utterances(should_stop=lambda: True))

    assert utterances == []


def test_record_while_reports_chunks_live(monkeypatch):
    """The desktop orb needs live amplitude while the key is held - each
    captured chunk must reach on_chunk before the recording ends."""
    import threading
    from contextlib import contextmanager

    import numpy as np

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


def test_stream_utterances_reports_chunks_live(monkeypatch):
    from contextlib import contextmanager

    import numpy as np

    from laris import audio_capture

    chunk = np.full((4,), 0.2, dtype=np.float32)
    seen = []

    @contextmanager
    def fake_stream(callback):
        callback(chunk.reshape(-1, 1), 4, None, None)
        yield

    monkeypatch.setattr(audio_capture, "_open_stream", fake_stream)

    vad = object.__new__(audio_capture.VadCapture)
    vad._model = object()
    vad._VADIterator = lambda model, **kwargs: lambda t, return_seconds: None

    stops = iter([False, True, True, True])
    list(vad.stream_utterances(should_stop=lambda: next(stops), on_chunk=seen.append))

    assert len(seen) == 1
