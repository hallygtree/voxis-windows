"""faster-whisper transcriber - device selection logic (mocked) and a real
CPU smoke transcription. The real-model test is marked slow."""
import numpy as np
import pytest


def _fake_model_class(devices, encode_fails_on=()):
    """WhisperModel stand-in recording every device it is built for. Devices in
    encode_fails_on raise on transcribe(), mimicking a CUDA build whose
    cuBLAS/cuDNN is missing (the model constructs, the first kernel dies)."""
    class FakeModel:
        def __init__(self, model, device, compute_type, **kw):
            devices.append((device, compute_type))
            self._device = device

        def transcribe(self, audio, **kw):
            if self._device in encode_fails_on:
                raise RuntimeError("Library cublas64_12.dll is not found")
            return iter(()), None

    return FakeModel


def test_device_selection_prefers_cuda_when_it_actually_runs(monkeypatch):
    import laris.stt_faster as mod

    devices = []
    monkeypatch.setattr(mod, "_cuda_available", lambda: True)
    monkeypatch.setattr(mod, "WhisperModel", _fake_model_class(devices))
    t = mod.FasterWhisperTranscriber()
    assert devices == [("cuda", "float16")]
    assert (t.device, t.compute_type) == ("cuda", "float16")


def test_device_selection_falls_back_to_cpu(monkeypatch):
    import laris.stt_faster as mod

    devices = []
    monkeypatch.setattr(mod, "_cuda_available", lambda: False)
    monkeypatch.setattr(mod, "WhisperModel", _fake_model_class(devices))
    t = mod.FasterWhisperTranscriber()
    assert devices == [("cpu", "int8")]
    assert (t.device, t.compute_type) == ("cpu", "int8")


def test_cuda_enumerated_but_broken_falls_back_to_cpu(monkeypatch, capsys):
    """Regression: an NVIDIA driver with no cuBLAS/cuDNN makes
    get_cuda_device_count() report a device, the model build succeed, and the
    first encode() raise - which killed the windowed engine at boot."""
    import laris.stt_faster as mod

    devices = []
    monkeypatch.setattr(mod, "_cuda_available", lambda: True)
    monkeypatch.setattr(
        mod, "WhisperModel", _fake_model_class(devices, encode_fails_on=("cuda",))
    )
    t = mod.FasterWhisperTranscriber()

    assert devices == [("cuda", "float16"), ("cpu", "int8")]
    assert (t.device, t.compute_type) == ("cpu", "int8")
    # the reason must reach the log, or the fallback is undebuggable
    assert "cublas64_12.dll" in capsys.readouterr().out


def test_warm_survives_broken_cuda(monkeypatch):
    """warm() is called unguarded by daemon.run - it must not raise."""
    import laris.stt_faster as mod

    monkeypatch.setattr(mod, "_cuda_available", lambda: True)
    monkeypatch.setattr(
        mod, "WhisperModel", _fake_model_class([], encode_fails_on=("cuda",))
    )
    mod.FasterWhisperTranscriber().warm()


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
