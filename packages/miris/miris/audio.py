"""Torch-free audio conversion shared by the capture and transcribe paths.

Both ends need the same two operations - fold N channels into one and drop to
16 kHz - and they used to be implemented twice, differently and both wrong:
the loopback tap kept only the left channel, and the transcriber reached for
torchaudio, which does not exist in the Windows bundle (B3).
"""
import numpy as np

TARGET_SR = 16000


def downmix_to_mono(frames: np.ndarray) -> np.ndarray:
    """(n, channels) or (n,) float array -> (n,) mono, averaging the channels.

    Averaging rather than taking channel 0: system audio is routinely
    hard-panned (a meeting app placing a participant fully on the right), and
    keeping one channel would drop that speaker from the transcript entirely
    while still producing a plausible-looking WAV.
    """
    audio = np.asarray(frames, dtype=np.float32)
    if audio.ndim == 1:
        return audio
    if audio.ndim != 2:
        raise ValueError(f"expected 1-D or 2-D audio, got shape {audio.shape}")
    if audio.shape[1] == 1:
        return audio[:, 0]
    return audio.mean(axis=1)


def resample_to_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    """Downsample mono float audio to 16 kHz with an anti-alias filter.

    Plain decimation (`audio[::3]`) folds everything above 8 kHz back into the
    speech band as aliasing noise, which Whisper hears as garbage. Averaging
    each block of `factor` samples is a boxcar low-pass whose nulls land
    exactly on the new sample rate and its harmonics, so the images that
    decimation would fold down are attenuated first.

    Upsampling is deliberately not supported: every capture path feeds this at
    >= 16 kHz, so a lower rate means the device was misconfigured and should
    be reported, not silently interpolated into fake bandwidth.
    """
    audio = np.asarray(audio, dtype=np.float32)
    if sr == TARGET_SR:
        return audio
    if sr < TARGET_SR:
        raise ValueError(
            f"cannot upsample {sr} Hz to {TARGET_SR} Hz: miris captures at "
            f"{TARGET_SR} Hz or above, so this file did not come from a "
            "supported capture path"
        )
    if len(audio) == 0:
        return audio

    if sr % TARGET_SR == 0:
        factor = sr // TARGET_SR
        usable = len(audio) - (len(audio) % factor)
        if usable == 0:
            return audio[:0]
        return audio[:usable].reshape(-1, factor).mean(axis=1)

    # Non-integer ratio (e.g. 44100 -> 16000): low-pass, then resample onto the
    # target grid by linear interpolation.
    window = int(round(sr / TARGET_SR))
    if window > 1:
        kernel = np.ones(window, dtype=np.float32) / window
        audio = np.convolve(audio, kernel, mode="same").astype(np.float32)
    n_out = int(len(audio) * TARGET_SR / sr)
    if n_out == 0:
        return audio[:0]
    positions = np.arange(n_out, dtype=np.float64) * (sr / TARGET_SR)
    return np.interp(positions, np.arange(len(audio)), audio).astype(np.float32)
