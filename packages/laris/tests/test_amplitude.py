import numpy as np

from laris.amplitude import compute_amplitude


def test_compute_amplitude_of_silence_is_zero():
    assert compute_amplitude(np.zeros(100, dtype=np.float32)) == 0.0


def test_compute_amplitude_of_empty_buffer_is_zero():
    assert compute_amplitude(np.array([], dtype=np.float32)) == 0.0


def test_compute_amplitude_scales_with_loudness():
    quiet = np.full(100, 0.05, dtype=np.float32)
    loud = np.full(100, 0.3, dtype=np.float32)
    assert compute_amplitude(quiet) < compute_amplitude(loud)


def test_compute_amplitude_is_capped_at_one():
    very_loud = np.full(100, 1.0, dtype=np.float32)
    assert compute_amplitude(very_loud) == 1.0


def test_conversational_speech_reads_visibly_on_the_orb():
    # live-measured: normal dictation lands around RMS 0.02 on the MacBook
    # mic; linear gain mapped it to ~0.08 and the orb looked frozen
    conversational = np.full(100, 0.02, dtype=np.float32)
    assert compute_amplitude(conversational) >= 0.25
