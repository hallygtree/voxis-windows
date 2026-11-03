import numpy as np
import pytest

from miris import audio


def _tone(freq: float, sr: int, seconds: float = 0.5) -> np.ndarray:
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    return np.sin(2 * np.pi * freq * t).astype(np.float32)


def _dominant_freq(x: np.ndarray, sr: int) -> float:
    spectrum = np.abs(np.fft.rfft(x))
    return float(np.fft.rfftfreq(len(x), 1 / sr)[int(np.argmax(spectrum))])


def test_downmix_averages_channels_instead_of_dropping_one():
    """Hard-panned system audio must survive: keeping only channel 0 would
    delete a speaker that a meeting app placed fully on the right."""
    left_silent = np.stack([np.zeros(100, dtype=np.float32),
                            np.ones(100, dtype=np.float32)], axis=1)
    mono = audio.downmix_to_mono(left_silent)
    assert mono.shape == (100,)
    assert np.allclose(mono, 0.5), "right-only content must not be discarded"


def test_downmix_passes_mono_through():
    mono = np.linspace(-1, 1, 64, dtype=np.float32)
    assert np.allclose(audio.downmix_to_mono(mono), mono)
    shaped = mono.reshape(-1, 1)
    assert audio.downmix_to_mono(shaped).shape == (64,)


def test_resample_48k_to_16k_preserves_a_speech_band_tone():
    sr = 48000
    out = audio.resample_to_16k(_tone(1000, sr), sr)
    assert len(out) == 16000 // 2
    assert abs(_dominant_freq(out, 16000) - 1000) < 20
    assert out.max() > 0.5, "signal must not be flattened by the filter"


def test_resample_attenuates_content_that_would_alias():
    """A 15 kHz tone is above the 8 kHz Nyquist of the target rate. Plain
    decimation would fold it down to 1 kHz - right into the speech band - and
    Whisper would transcribe the noise. The anti-alias filter must kill it."""
    sr = 48000
    tone = _tone(15000, sr)
    filtered = audio.resample_to_16k(tone, sr)
    aliased = tone[::3]  # what naive decimation produces
    assert np.abs(filtered).max() < 0.3 * np.abs(aliased).max()


def test_resample_is_identity_at_16k():
    x = _tone(440, 16000)
    out = audio.resample_to_16k(x, 16000)
    assert out is x or np.allclose(out, x)


def test_resample_handles_non_integer_ratio():
    sr = 44100
    out = audio.resample_to_16k(_tone(1000, sr), sr)
    assert abs(len(out) - 8000) <= 2
    assert abs(_dominant_freq(out, 16000) - 1000) < 30


def test_resample_refuses_to_upsample_with_a_clear_message():
    with pytest.raises(ValueError, match="cannot upsample"):
        audio.resample_to_16k(_tone(440, 8000), 8000)


def test_resample_tolerates_a_length_that_is_not_a_whole_number_of_blocks():
    out = audio.resample_to_16k(np.ones(48000 + 2, dtype=np.float32), 48000)
    assert len(out) == 16000
