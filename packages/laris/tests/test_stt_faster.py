"""faster-whisper transcriber - device selection logic (mocked) and a real
CPU smoke transcription. The real-model test is marked slow."""
import numpy as np
import pytest


def test_device_selection_prefers_cuda_when_available(monkeypatch):
    import laris.stt_faster as mod

    captured = {}

    class FakeModel:
        def __init__(self, model, device, compute_type, **kw):
            captured.update(device=device, compute_type=compute_type, model=model)

    monkeypatch.setattr(mod, "_cuda_available", lambda: True)
    monkeypatch.setattr(mod, "WhisperModel", FakeModel)
    mod.FasterWhisperTranscriber()
    assert captured["device"] == "cuda"
    assert captured["compute_type"] == "float16"


def test_device_selection_falls_back_to_cpu(monkeypatch):
    import laris.stt_faster as mod

    captured = {}

    class FakeModel:
        def __init__(self, model, device, compute_type, **kw):
            captured.update(device=device, compute_type=compute_type)

    monkeypatch.setattr(mod, "_cuda_available", lambda: False)
    monkeypatch.setattr(mod, "WhisperModel", FakeModel)
    mod.FasterWhisperTranscriber()
    assert captured["device"] == "cpu"
    assert captured["compute_type"] == "int8"


def test_transcribe_empty_returns_empty(monkeypatch):
    import laris.stt_faster as mod
    monkeypatch.setattr(mod, "_cuda_available", lambda: False)
    monkeypatch.setattr(mod, "WhisperModel", lambda *a, **k: object())
    t = mod.FasterWhisperTranscriber()
    assert t.transcribe(np.zeros(0, dtype=np.float32), 16000) == ""


@pytest.mark.slow
def test_real_cpu_transcription_smoke():
    """Downloads the real model once and transcribes 1s of a sine sweep -
    asserts it returns a string without raising."""
    from laris.stt_faster import FasterWhisperTranscriber
    t = FasterWhisperTranscriber()
    t.warm()
    audio = (0.1 * np.sin(2 * np.pi * 220 * np.arange(16000) / 16000)).astype(np.float32)
    result = t.transcribe(audio, 16000)
    assert isinstance(result, str)
