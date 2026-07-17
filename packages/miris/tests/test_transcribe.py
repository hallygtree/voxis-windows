import wave
from pathlib import Path

import numpy as np

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
    stereo = np.zeros(48000 * 2, dtype=np.float32)  # 1s of 48k stereo interleaved
    _write_wav(tmp_path / "b.wav", stereo, 48000, channels=2)
    loaded = transcribe.load_wav_mono16k(tmp_path / "b.wav")
    assert abs(len(loaded) - 16000) <= 1


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
