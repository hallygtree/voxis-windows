import importlib.util
import threading

import numpy as np
import pytest


def _missing(*modules):
    return [m for m in modules if importlib.util.find_spec(m) is None]


# Two supported profiles: macOS ships torch (silero VAD + DeepFilterNet3),
# the Windows bundle is torch-free by design (requirements-windows.txt). The
# tests below exercise the torch half and cannot pass on the Windows profile -
# skipping keeps the suite honest there instead of permanently red.
requires_torch = pytest.mark.skipif(
    bool(_missing("torch")),
    reason="torch profile only; the Windows engine bundle is torch-free",
)
requires_deepfilternet = pytest.mark.skipif(
    bool(_missing("torch", "torchaudio", "df")),
    reason="DeepFilterNet3 profile only; the Windows engine bundle is torch-free",
)


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


@requires_torch
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


@requires_torch
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


def test_denoise_off_returns_audio_unchanged():
    """When NOISE_REDUCTION=off, the denoise wrapper is a passthrough."""
    import numpy as np

    from laris.audio_capture import _denoise_chunk

    chunk = np.ones(512, dtype=np.float32) * 0.5
    result = _denoise_chunk(chunk, enabled=False)
    assert np.array_equal(result, chunk)


@requires_deepfilternet
def test_denoise_on_changes_audio():
    """When NOISE_REDUCTION=on and DFN3 is loaded, the output differs from input
    (a real denoiser changes the signal)."""
    import numpy as np

    from laris.audio_capture import _denoise_chunk

    chunk = np.random.randn(512 * 8).astype(np.float32) * 0.3
    result = _denoise_chunk(chunk, enabled=True)
    assert result.dtype == np.float32
    assert len(result) == len(chunk)
    assert not np.array_equal(result, chunk)


def test_denoise_on_is_passthrough_without_deepfilternet(monkeypatch):
    """Torch-free profile (Windows): DFN3 cannot load, so NOISE_REDUCTION=on
    must degrade to passthrough and return the audio intact rather than raise -
    the voice loop would otherwise lose the utterance."""
    import numpy as np

    from laris import audio_capture

    monkeypatch.setattr(audio_capture, "_dfn_state", (None, None))

    chunk = np.random.randn(512 * 8).astype(np.float32) * 0.3
    result = audio_capture._denoise_chunk(chunk, enabled=True)

    assert np.array_equal(result, chunk)
    assert result.dtype == np.float32


def test_denoise_handles_short_chunk():
    """Shorter-than-frame chunks must not crash the denoiser — buffer them."""
    import numpy as np

    from laris.audio_capture import _denoise_chunk

    chunk = np.ones(100, dtype=np.float32) * 0.5
    result = _denoise_chunk(chunk, enabled=True)
    assert len(result) == 100
    assert result.dtype == np.float32
