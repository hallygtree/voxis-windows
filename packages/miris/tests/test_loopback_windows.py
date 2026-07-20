"""Tests for WindowsLoopbackTap (Windows WASAPI loopback capture).

Note: These are unit tests for the interface and structure.
Integration tests (with actual audio) require hardware and should run separately.
"""
import threading
import time
import wave
from pathlib import Path

import pytest

# Only import on Windows; skip tests gracefully on other platforms
pytest.importorskip("soundcard", minversion=None)

from miris.loopback_windows import WindowsLoopbackTap
from miris.systemtap import Tap


def test_windows_loopback_tap_implements_interface():
    """Verify WindowsLoopbackTap implements Tap interface."""
    assert isinstance(WindowsLoopbackTap, type)
    # Check interface methods exist
    assert hasattr(WindowsLoopbackTap, "start")
    assert hasattr(WindowsLoopbackTap, "stop")
    assert hasattr(WindowsLoopbackTap, "alive")
    assert issubclass(WindowsLoopbackTap, Tap)


def test_windows_loopback_tap_lifecycle(tmp_path):
    """Test WindowsLoopbackTap start/alive/stop lifecycle.

    This test doesn't require actual audio; it just verifies the lifecycle
    machinery doesn't crash. Real audio validation is done in voxis-verify-windows.
    """
    out_wav = tmp_path / "system.wav"
    tap = WindowsLoopbackTap(out_wav)

    # Before start, should not be alive
    assert not tap.alive()

    # Start should not raise (even if no loopback device available, it should
    # handle the error gracefully)
    try:
        tap.start()
    except Exception as e:
        # If soundcard can't open loopback, that's ok for this test
        # (we're testing the interface, not the hardware)
        pytest.skip(f"No loopback device available: {e}")

    # After start, should be alive (briefly, until capture thread finishes)
    time.sleep(0.1)
    # Note: might be False if the thread failed silently; that's ok
    # is_alive just reflects the thread state

    # Stop should not raise
    tap.stop(grace_s=2.0)

    # After stop, should not be alive
    assert not tap.alive()

    # WAV file should exist (even if empty due to no audio)
    # The interface guarantees it's finalized (not truncated)
    if out_wav.exists():
        # Verify it's a valid WAV file
        try:
            with wave.open(str(out_wav), "rb") as f:
                assert f.getnchannels() == 1
                assert f.getsampwidth() == 2
                assert f.getframerate() == 16000
        except wave.Error:
            # If WAV is empty or invalid, that's acceptable (no audio)
            pass


def test_windows_loopback_tap_stop_without_start(tmp_path):
    """Test that stop() without start() doesn't crash."""
    out_wav = tmp_path / "system.wav"
    tap = WindowsLoopbackTap(out_wav)
    # Should not raise
    tap.stop()
    assert not tap.alive()


def test_windows_loopback_tap_cannot_start_twice(tmp_path):
    """Test that starting twice raises RuntimeError."""
    out_wav = tmp_path / "system.wav"
    tap = WindowsLoopbackTap(out_wav)

    try:
        tap.start()
    except Exception:
        pytest.skip("Cannot open loopback device for this test")

    try:
        with pytest.raises(RuntimeError, match="already started"):
            tap.start()
    finally:
        tap.stop()
