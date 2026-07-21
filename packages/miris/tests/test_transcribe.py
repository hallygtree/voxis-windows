import wave
from pathlib import Path

import numpy as np
import pytest

from miris import transcribe
from miris.transcribe import Segment


def _write_wav(path: Path, audio: np.ndarray, sr: int, channels: int = 1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def test_load_wav_16k_mono_roundtrip(tmp_path):
    audio = np.sin(np.linspace(0, 100, 16000)).astype(np.float32) * 0.5
    _write_wav(tmp_path / "a.wav", audio, 16000)
    loaded = transcribe.load_wav_mono16k(tmp_path / "a.wav")
    assert loaded.shape == (16000,)
    assert np.abs(loaded - audio).max() < 0.01


def test_load_wav_downmixes_and_resamples(tmp_path):
    """Rewritten for the B3 contract: the downmix+resample still happens (the
    macOS helper writes at the device rate, typically 48 kHz stereo), but it
    is now pure numpy - importing torch/torchaudio here would blow up in the
    torch-free Windows bundle.

    The previous version fed all-zeros and only checked the output length, so
    it passed for any implementation that returned the right number of
    samples, including a broken one. It now asserts the signal survives.
    """
    sr = 48000
    t = np.arange(sr, dtype=np.float32) / sr
    left = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    right = np.zeros(sr, dtype=np.float32)  # hard-panned: must not be dropped
    interleaved = np.empty(sr * 2, dtype=np.float32)
    interleaved[0::2], interleaved[1::2] = left, right
    _write_wav(tmp_path / "b.wav", interleaved, sr, channels=2)

    loaded = transcribe.load_wav_mono16k(tmp_path / "b.wav")

    assert abs(len(loaded) - 16000) <= 1
    spectrum = np.abs(np.fft.rfft(loaded))
    peak_hz = np.fft.rfftfreq(len(loaded), 1 / 16000)[int(np.argmax(spectrum))]
    assert abs(peak_hz - 1000) < 20, "the 1 kHz tone must survive the resample"
    # averaged with a silent right channel -> half amplitude, not zero
    assert 0.2 < np.abs(loaded).max() < 0.75


def test_load_wav_does_not_import_torch(tmp_path, monkeypatch):
    """B3: the whole point is that the Windows bundle ships no torch. Make the
    import fail loudly so a regression cannot hide behind a dev machine that
    happens to have torch installed."""
    import builtins

    real_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "torchaudio", "silero_vad"}:
            raise AssertionError(f"load_wav_mono16k must not import {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    _write_wav(tmp_path / "c.wav", np.zeros(48000 * 2, dtype=np.float32),
               48000, channels=2)
    assert len(transcribe.load_wav_mono16k(tmp_path / "c.wav")) == 16000


def test_load_wav_rejects_a_rate_below_16k_with_a_clear_message(tmp_path):
    _write_wav(tmp_path / "slow.wav", np.zeros(8000, dtype=np.float32), 8000)
    with pytest.raises(ValueError, match="cannot upsample"):
        transcribe.load_wav_mono16k(tmp_path / "slow.wav")


def test_load_wav_tolerates_truncated_stereo(tmp_path):
    path = tmp_path / "trunc.wav"
    _write_wav(path, np.zeros(3200, dtype=np.float32), 16000, channels=2)
    with open(path, "r+b") as f:  # chop 2 bytes so samples % channels != 0
        f.truncate(path.stat().st_size - 2)
    loaded = transcribe.load_wav_mono16k(path)
    assert len(loaded) > 0


def test_transcribe_channel_uses_spans_and_transcriber(tmp_path):
    audio = np.zeros(32000, dtype=np.float32)  # 2s @16k
    _write_wav(tmp_path / "c.wav", audio, 16000)

    class FakeTranscriber:
        def transcribe(self, chunk):
            return f"len={len(chunk)}"

    spans = lambda a, sr=16000: [(0, 16000), (16000, 32000)]
    segs = transcribe.transcribe_channel(tmp_path / "c.wav", "Eu", FakeTranscriber(), spans_fn=spans)
    assert segs == [
        Segment(0.0, 1.0, "Eu", "len=16000"),
        Segment(1.0, 2.0, "Eu", "len=16000"),
    ]


class _FWSegment:
    """Shape of a faster-whisper segment: start/end in seconds, leading-space text."""

    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class VadTranscriber:
    """A transcriber exposing transcribe_with_vad, like FasterWhisperTranscriber."""

    def __init__(self, segments):
        self._segments = segments
        self.saw_spans_fn = False

    def transcribe_with_vad(self, audio, sample_rate=16000):
        return self._segments


def test_transcribe_channel_prefers_builtin_vad_and_keeps_its_timestamps(tmp_path):
    """B3: on Windows the VAD is faster-whisper's own (Silero via onnxruntime),
    not silero_vad+torch. With vad_filter=True faster-whisper runs
    restore_speech_timestamps (transcribe.py:1010), so segment.start/.end are
    already on the original audio's timeline - they must be carried through
    verbatim, not rescaled as if they were sample indices."""
    _write_wav(tmp_path / "d.wav", np.zeros(32000, dtype=np.float32), 16000)

    def exploding_spans(audio, sr=16000):
        raise AssertionError("must not fall back to the torch/silero VAD")

    segs = transcribe.transcribe_channel(
        tmp_path / "d.wav", "Eles",
        VadTranscriber([_FWSegment(0.0, 1.4, " Bom dia"),
                        _FWSegment(2.5, 4.0, " tudo certo")]),
        spans_fn=exploding_spans)

    assert segs == [
        Segment(0.0, 1.4, "Eles", "Bom dia"),
        Segment(2.5, 4.0, "Eles", "tudo certo"),
    ]


def test_transcribe_channel_drops_empty_vad_segments(tmp_path):
    _write_wav(tmp_path / "e.wav", np.zeros(16000, dtype=np.float32), 16000)
    segs = transcribe.transcribe_channel(
        tmp_path / "e.wav", "Eles",
        VadTranscriber([_FWSegment(0.0, 1.0, "   "),
                        _FWSegment(1.0, 2.0, " oi")]))
    assert segs == [Segment(1.0, 2.0, "Eles", "oi")]


def test_vad_segments_merge_into_a_coherent_two_speaker_timeline(tmp_path):
    """The merged transcript is what the LLM summarises, so the two channels'
    timestamps have to stay comparable after the VAD swap."""
    _write_wav(tmp_path / "f.wav", np.zeros(16000 * 5, dtype=np.float32), 16000)
    mine = transcribe.transcribe_channel(
        tmp_path / "f.wav", "Eu",
        VadTranscriber([_FWSegment(0.0, 2.0, " oi"),
                        _FWSegment(65.0, 66.0, " tchau")]))
    theirs = transcribe.transcribe_channel(
        tmp_path / "f.wav", "Eles",
        VadTranscriber([_FWSegment(2.5, 4.0, " olá")]))

    assert transcribe.merge(mine, theirs) == (
        "[00:00] Eu: oi\n[00:02] Eles: olá\n[01:05] Eu: tchau"
    )


def test_collapse_repetitions_caps_hallucinated_runs():
    text = "essas " + "pessoas " * 200 + "também"
    result = transcribe.collapse_repetitions(text.strip())
    assert result == "essas pessoas pessoas pessoas também"
    assert transcribe.collapse_repetitions("um dois três") == "um dois três"


def test_merge_interleaves_by_timestamp():
    me = [Segment(0.0, 1.0, "Eu", "oi"), Segment(65.0, 66.0, "Eu", "tchau")]
    them = [Segment(2.5, 4.0, "Eles", "olá")]
    assert transcribe.merge(me, them) == (
        "[00:00] Eu: oi\n[00:02] Eles: olá\n[01:05] Eu: tchau"
    )
