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


def test_watch_stop_sentinel_sets_stop_and_exits(tmp_path):
    stop = threading.Event()
    watcher = threading.Thread(
        target=recorder.watch_stop_sentinel, args=(tmp_path, stop, 0.01), daemon=True)
    watcher.start()
    assert not stop.wait(0.05), "must not stop before the sentinel exists"
    (tmp_path / recorder.STOP_SENTINEL).touch()
    assert stop.wait(2.0), "sentinel must set the stop event"
    watcher.join(timeout=2.0)
    assert not watcher.is_alive()


def test_watch_stop_sentinel_exits_when_stopped_by_other_means(tmp_path):
    """The watcher is not the only way to stop; it must not outlive the run."""
    stop = threading.Event()
    watcher = threading.Thread(
        target=recorder.watch_stop_sentinel, args=(tmp_path, stop, 0.01), daemon=True)
    watcher.start()
    stop.set()
    watcher.join(timeout=2.0)
    assert not watcher.is_alive()


def test_record_stops_via_sentinel_and_finalizes_wavs(tmp_path):
    """B2 end to end: dropping the sentinel (no signal involved) must end the
    recording with a WAV whose header was patched shut. On Windows there is no
    deliverable SIGTERM - os.kill is TerminateProcess - so this file handshake
    is the only path that finalizes mic.wav/system.wav."""
    stop = threading.Event()
    threading.Thread(target=recorder.watch_stop_sentinel,
                     args=(tmp_path, stop, 0.01), daemon=True).start()

    class FakeStream:
        def __init__(self, cb):
            self._cb = cb

        def __enter__(self):
            for _ in range(3):
                self._cb(np.zeros((1600, 1), dtype=np.float32), 1600, None, None)
            return self

        def __exit__(self, *a):
            return False

    taps = []

    def tap_factory(out_wav, binary=None):
        taps.append(FakeTap(out_wav))
        return taps[-1]

    threading.Timer(0.15, (tmp_path / recorder.STOP_SENTINEL).touch).start()
    recorder.record(tmp_path, stop, tap_factory=tap_factory,
                    open_stream=lambda cb: FakeStream(cb))

    assert stop.is_set()
    assert taps[0].stopped, "the system tap must be closed too"
    with wave.open(str(tmp_path / "mic.wav"), "rb") as f:
        assert f.getnframes() == 3 * 1600  # header patched, not left at 0
