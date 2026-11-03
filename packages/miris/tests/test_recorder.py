import time
import threading
import wave
from pathlib import Path

import numpy as np

from miris import recorder
from miris import session


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

    def bytes_written(self):
        return self.out_wav.stat().st_size

    def stop(self, grace_s=5.0):
        self.stopped = True


def test_record_writes_both_channels_and_stops(tmp_path):
    session.create(tmp_path)
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
    recorder.record(
        tmp_path, stop, tap_factory=tap_factory, open_stream=lambda cb: FakeStream(cb)
    )
    timer.cancel()

    assert taps[0].stopped
    assert (tmp_path / "system.wav").exists()
    with wave.open(str(tmp_path / "mic.wav"), "rb") as f:
        assert f.getnframes() == 3 * 1600


class GrowingFakeTap:
    def __init__(self, out_wav, die_after_checks=None, seconds=0.1):
        self.out_wav = Path(out_wav)
        self.die_after_checks = die_after_checks
        self.seconds = seconds
        self.checks = 0
        self.stopped = False

    def start(self):
        with wave.open(str(self.out_wav), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(48_000)
            frames = int(48_000 * self.seconds)
            wav.writeframes(np.zeros(frames * 2, dtype=np.int16).tobytes())

    def bytes_written(self):
        return self.out_wav.stat().st_size

    def alive(self):
        self.checks += 1
        return self.die_after_checks is None or self.checks < self.die_after_checks

    def stop(self, grace_s=5.0):
        self.stopped = True


def fake_stream(chunks, stop=None, status=None):
    class Stream:
        def __init__(self, callback):
            self.callback = callback

        def __enter__(self):
            for chunk in chunks:
                self.callback(chunk.reshape(-1, 1), len(chunk), None, status)
            if stop is not None:
                stop.set()
            return self

        def __exit__(self, *args):
            return False

    return Stream


def test_recording_state_requires_frames_from_both_channels(tmp_path):
    session.create(tmp_path)
    tap = GrowingFakeTap(tmp_path / "system.wav")
    stop = threading.Event()
    state = recorder.record(
        tmp_path,
        stop,
        tap_factory=lambda p: tap,
        open_stream=fake_stream([np.zeros(1_600, dtype=np.float32)], stop=stop),
    )
    assert state is session.SessionState.CAPTURED


def test_dead_system_tap_interrupts_capture(tmp_path):
    session.create(tmp_path)
    tap = GrowingFakeTap(tmp_path / "system.wav", die_after_checks=2)
    result = recorder.record(
        tmp_path,
        threading.Event(),
        tap_factory=lambda p: tap,
        open_stream=fake_stream([np.zeros(1_600, dtype=np.float32)]),
    )
    assert result is session.SessionState.INTERRUPTED
    assert session.load(tmp_path).error.code == "system_tap_died"


def test_microphone_callback_error_interrupts_capture(tmp_path):
    session.create(tmp_path)
    result = recorder.record(
        tmp_path,
        threading.Event(),
        tap_factory=lambda p: GrowingFakeTap(p),
        open_stream=fake_stream(
            [np.zeros(1_600, dtype=np.float32)], status="input overflow"
        ),
    )
    assert result is session.SessionState.INTERRUPTED
    assert session.load(tmp_path).error.code == "microphone_error"


def test_queue_overflow_is_not_silent(tmp_path):
    session.create(tmp_path)
    chunks = [np.zeros(1_600, dtype=np.float32)] * (recorder.QUEUE_CHUNKS + 1)
    result = recorder.record(
        tmp_path,
        threading.Event(),
        tap_factory=lambda p: GrowingFakeTap(p),
        open_stream=fake_stream(chunks),
    )
    assert result is session.SessionState.INTERRUPTED
    assert session.load(tmp_path).error.code == "microphone_queue_overflow"


class FakeClock:
    def __init__(self, step=1.0):
        self.value = 0.0
        self.step = step

    def __call__(self):
        self.value += self.step
        return self.value


def test_missing_first_microphone_frame_fails_startup(tmp_path):
    session.create(tmp_path)
    stop = threading.Event()
    result = recorder.record(
        tmp_path,
        stop,
        tap_factory=lambda p: GrowingFakeTap(p),
        open_stream=fake_stream([]),
        now=FakeClock(),
    )
    assert result is session.SessionState.FAILED
    assert session.load(tmp_path).error.code == "microphone_start_timeout"


def test_missing_first_system_frame_fails_startup(tmp_path):
    session.create(tmp_path)

    class EmptyTap(GrowingFakeTap):
        def start(self):
            self.out_wav.write_bytes(b"RIFF")

    stop = threading.Event()
    result = recorder.record(
        tmp_path,
        stop,
        tap_factory=lambda p: EmptyTap(p),
        open_stream=fake_stream([np.zeros(1600, dtype=np.float32)]),
        now=FakeClock(),
    )
    assert result is session.SessionState.FAILED
    assert session.load(tmp_path).error.code == "system_tap_start_timeout"


def test_two_second_stall_interrupts_recording(tmp_path):
    session.create(tmp_path)
    tap = GrowingFakeTap(tmp_path / "system.wav")
    result = recorder.record(
        tmp_path,
        threading.Event(),
        tap_factory=lambda p: tap,
        open_stream=fake_stream([np.zeros(1600, dtype=np.float32)]),
        now=FakeClock(),
    )
    assert result is session.SessionState.INTERRUPTED
    assert session.load(tmp_path).error.code == "system_tap_stalled"


def test_writer_exception_interrupts_recording(tmp_path, monkeypatch):
    session.create(tmp_path)
    original = recorder.WavWriter.write

    def broken_write(self, chunk):
        raise OSError("disk full")

    monkeypatch.setattr(recorder.WavWriter, "write", broken_write)
    result = recorder.record(
        tmp_path,
        threading.Event(),
        tap_factory=lambda p: GrowingFakeTap(p),
        open_stream=fake_stream([np.zeros(1600, dtype=np.float32)]),
    )
    assert result is session.SessionState.INTERRUPTED
    assert session.load(tmp_path).error.code == "writer_error"
    monkeypatch.setattr(recorder.WavWriter, "write", original)


def test_manifest_write_failure_interrupts_capture(tmp_path, monkeypatch):
    session.create(tmp_path)

    def broken_heartbeat(session_dir, mic_frames, system_bytes):
        raise OSError("manifest disk full")

    monkeypatch.setattr(recorder, "_heartbeat", broken_heartbeat)
    result = recorder.record(
        tmp_path,
        threading.Event(),
        tap_factory=lambda p: GrowingFakeTap(p),
        open_stream=fake_stream([np.zeros(1600, dtype=np.float32)]),
        now=FakeClock(),
    )
    assert result is session.SessionState.INTERRUPTED
    assert session.load(tmp_path).error.code == "manifest_error"


def test_microphone_stall_interrupts_while_system_grows(tmp_path):
    session.create(tmp_path)

    class GrowingTap(GrowingFakeTap):
        def bytes_written(self):
            with open(self.out_wav, "ab") as f:
                f.write(b"x" * 100)
            return self.out_wav.stat().st_size

    result = recorder.record(
        tmp_path,
        threading.Event(),
        tap_factory=lambda p: GrowingTap(p),
        open_stream=fake_stream([np.zeros(1600, dtype=np.float32)]),
        now=FakeClock(),
    )
    assert result is session.SessionState.INTERRUPTED
    assert session.load(tmp_path).error.code == "microphone_stalled"


def test_normal_stop_rejects_duration_delta_over_two_seconds(tmp_path):
    session.create(tmp_path)
    stop = threading.Event()
    result = recorder.record(
        tmp_path,
        stop,
        tap_factory=lambda p: GrowingFakeTap(p, seconds=3),
        open_stream=fake_stream([np.zeros(1600, dtype=np.float32)], stop=stop),
    )
    assert result is session.SessionState.INTERRUPTED
    assert session.load(tmp_path).error.code == "capture_invalid"


# --- Windows fork ---


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
    session.create(tmp_path)
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
