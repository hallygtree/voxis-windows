import threading
import time
import wave
from pathlib import Path

import numpy as np

from miris import recorder


def test_wavwriter_roundtrip(tmp_path):
    path = tmp_path / "m.wav"
    w = recorder.WavWriter(path, sample_rate=16000)
    w.write(np.ones(1600, dtype=np.float32) * 0.5)
    w.close()
    with wave.open(str(path), "rb") as f:
        assert f.getnchannels() == 1
        assert f.getframerate() == 16000
        assert f.getnframes() == 1600


class FakeTap:
    def __init__(self, out_wav, binary=None):
        self.out_wav = Path(out_wav)
        self.stopped = False

    def start(self):
        self.out_wav.write_bytes(b"RIFF")

    def alive(self):
        return not self.stopped

    def stop(self, grace_s=5.0):
        self.stopped = True


def test_record_writes_both_channels_and_stops(tmp_path):
    stop = threading.Event()
    chunks = [np.zeros(1600, dtype=np.float32)] * 3

    class FakeStream:
        def __init__(self, cb):
            self._cb = cb

        def __enter__(self):
            for c in chunks:
                self._cb(c.reshape(-1, 1), len(c), None, None)
            return self

        def __exit__(self, *a):
            return False

    taps = []

    def tap_factory(out_wav, binary=None):
        tap = FakeTap(out_wav)
        taps.append(tap)
        return tap

    timer = threading.Timer(0.3, stop.set)
    timer.start()
    recorder.record(tmp_path, stop, tap_factory=tap_factory,
                    open_stream=lambda cb: FakeStream(cb))
    timer.cancel()

    assert taps[0].stopped
    assert (tmp_path / "system.wav").exists()
    with wave.open(str(tmp_path / "mic.wav"), "rb") as f:
        assert f.getnframes() == 3 * 1600
