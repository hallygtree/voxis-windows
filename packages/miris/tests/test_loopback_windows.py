"""Tests for WindowsLoopbackTap (Windows WASAPI loopback capture).

These deliberately do NOT skip when `soundcard` is absent: the lifecycle, the
WAV finalization and the error reporting are pure Python and are exactly
where the bugs were. Only the test that touches a real device is gated.
"""
import sys
import threading
import wave

import numpy as np
import pytest

from miris.loopback_windows import WindowsLoopbackTap
from miris.systemtap import Tap


def _has_soundcard() -> bool:
    try:
        import soundcard  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


needs_device = pytest.mark.skipif(
    not (_has_soundcard() and sys.platform == "win32"),
    reason="needs a real WASAPI loopback device",
)


class FakeRecorder:
    """Stands in for soundcard's recorder context manager."""

    def __init__(self, chunks, fail_with=None):
        self._chunks = list(chunks)
        self._fail_with = fail_with
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def record(self, n):
        self.reads += 1
        if self._fail_with is not None:
            raise self._fail_with
        if self._chunks:
            return self._chunks.pop(0)
        return np.zeros((n, 2), dtype=np.float32)


def _wait_until(predicate, timeout=3.0):
    deadline = threading.Event()
    for _ in range(int(timeout / 0.01)):
        if predicate():
            return True
        deadline.wait(0.01)
    return predicate()


def test_implements_tap_interface():
    assert issubclass(WindowsLoopbackTap, Tap)


def test_stop_without_start_does_not_crash(tmp_path):
    tap = WindowsLoopbackTap(tmp_path / "system.wav")
    tap.stop()
    assert not tap.alive()


def test_missing_device_raises_with_context_instead_of_vanishing(tmp_path, monkeypatch):
    """The original code caught this into warnings.warn from a background
    thread. The engine is packaged windowed, so that meant an empty
    system.wav and no explanation anywhere."""
    def boom(*a, **k):
        raise RuntimeError("no default playback device: nothing to tap")

    monkeypatch.setattr("miris.loopback_windows.open_default_loopback", boom)
    tap = WindowsLoopbackTap(tmp_path / "system.wav")
    with pytest.raises(RuntimeError, match="no default playback device"):
        tap.start()
    assert tap.error is not None
    assert not tap.alive()


def test_capture_writes_downmixed_16k_audio_and_finalizes_wav(tmp_path, monkeypatch):
    sr, out = 48000, tmp_path / "system.wav"
    t = np.arange(4800, dtype=np.float32) / sr
    left = np.sin(2 * np.pi * 1000 * t).astype(np.float32)
    chunk = np.stack([left, np.zeros_like(left)], axis=1)  # hard-panned left
    rec = FakeRecorder([chunk] * 5)
    monkeypatch.setattr("miris.loopback_windows.open_default_loopback",
                        lambda *a, **k: rec)

    tap = WindowsLoopbackTap(out)
    tap.start()
    _wait_until(lambda: rec.reads >= 5)
    tap.stop()

    assert not tap.alive()
    with wave.open(str(out), "rb") as f:
        assert f.getnchannels() == 1
        assert f.getframerate() == 16000
        assert f.getsampwidth() == 2
        assert f.getnframes() > 0, "header must be patched shut, not left at 0"
        data = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    # left-only content must survive the downmix (averaging, not channel 0)
    assert np.abs(data).max() > 3000


def test_repeated_device_failures_give_up_instead_of_spinning(tmp_path, monkeypatch):
    """A dead device used to be retried forever at full speed, burning a core
    for the length of the meeting and logging nothing after the first time."""
    rec = FakeRecorder([], fail_with=OSError("device disconnected"))
    monkeypatch.setattr("miris.loopback_windows.open_default_loopback",
                        lambda *a, **k: rec)

    tap = WindowsLoopbackTap(tmp_path / "system.wav")
    tap.start()
    _wait_until(lambda: tap.error is not None)
    tap.stop()

    assert tap.error is not None, "must record why capture died"
    assert "failed" in tap.error
    assert rec.reads <= 20, "must stop retrying, not spin"


def test_start_twice_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("miris.loopback_windows.open_default_loopback",
                        lambda *a, **k: FakeRecorder([]))
    tap = WindowsLoopbackTap(tmp_path / "system.wav")
    tap.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            tap.start()
    finally:
        tap.stop()


@needs_device
def test_real_default_speaker_exposes_a_loopback():
    """Regression for the actual B1 bug: the code used `speaker.loopback`,
    which does not exist on soundcard's Speaker (channels/id/name/play/player
    only), so capture died with AttributeError on every machine."""
    from miris.loopback_windows import open_default_loopback

    with open_default_loopback() as rec:
        frames = rec.record(4800)
    assert frames.shape[0] > 0
    assert frames.dtype == np.float32
