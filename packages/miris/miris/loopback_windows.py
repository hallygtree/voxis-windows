"""Windows WASAPI loopback system audio capture (in-process, thread-based)."""
import sys
import threading
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from miris.audio import TARGET_SR, downmix_to_mono, resample_to_16k
from miris.systemtap import Tap

# What we ask the loopback device for. soundcard resamples internally if the
# endpoint runs at another rate, so this is a request, not an assumption.
LOOPBACK_SAMPLE_RATE = 48000
TARGET_SAMPLE_RATE = TARGET_SR
CHUNK_FRAMES = 4800  # 100 ms @ 48 kHz
# A loopback that keeps throwing is broken (device unplugged, endpoint torn
# down). Give up instead of spinning on the error for the whole meeting.
MAX_CONSECUTIVE_ERRORS = 10


def _log(message: str) -> None:
    """Report to stderr, which `miris start` redirects into recorder.log.

    Not `warnings.warn`: the default warning filter shows a given warning once
    per call site, so a device failing every 100 ms would be reported once and
    then swallowed - and warnings can be disabled outright in a frozen build.
    This process is packaged windowed, so stderr into the log file is the only
    channel a human ever sees.
    """
    print(f"[loopback] {message}", file=sys.stderr, flush=True)


def open_default_loopback(sample_rate: int = LOOPBACK_SAMPLE_RATE):
    """Resolve the default speaker's loopback recorder.

    `soundcard` has no `Speaker.loopback` attribute - a Speaker only exposes
    channels/id/name/play/player. Loopback is reached by asking for a
    *microphone* with the speaker's id and include_loopback=True.
    """
    import soundcard as sc

    speaker = sc.default_speaker()
    if speaker is None:
        raise RuntimeError(
            "no default playback device: Windows has no active speaker to tap "
            "(check Sound settings; a Bluetooth headset that is off counts)"
        )
    loopback = sc.get_microphone(id=str(speaker.name), include_loopback=True)
    if loopback is None:
        raise RuntimeError(
            f"no WASAPI loopback for default speaker {speaker.name!r}"
        )
    return loopback.recorder(samplerate=sample_rate, channels=None)


class WindowsLoopbackTap(Tap):
    """Capture system audio via WASAPI loopback in a background thread.

    - Reads the default speaker's loopback endpoint
    - Folds all channels into mono and drops to 16 kHz in numpy (no torch)
    - Writes 16-bit PCM to out_wav incrementally
    """

    def __init__(self, out_wav: Path):
        self.out_wav = out_wav
        self.error: Optional[str] = None  # set when capture could not run
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wav_file: Optional[wave.Wave_write] = None
        self._wav_lock = threading.Lock()
        self._started = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("WindowsLoopbackTap already started")
        self.error = None
        with self._wav_lock:
            self._wav_file = wave.open(str(self.out_wav), "wb")
            self._wav_file.setnchannels(1)
            self._wav_file.setsampwidth(2)
            self._wav_file.setframerate(TARGET_SAMPLE_RATE)
        self._stop_event.clear()
        self._started.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=False)
        self._thread.start()
        # Surface an unusable device to the caller instead of letting it die in
        # a background thread: this process is windowed, so a thread that fails
        # quietly means an empty system.wav and a meeting transcript missing
        # every other participant, with nothing to show for it.
        self._started.wait(timeout=5.0)
        if self.error is not None:
            self.stop()
            raise RuntimeError(self.error)

    def alive(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stop_event.is_set()
        )

    def stop(self, grace_s: float = 5.0) -> None:
        thread, self._thread = self._thread, None
        self._stop_event.set()
        if thread is not None:
            thread.join(timeout=grace_s)
            if thread.is_alive():
                _log(f"capture thread did not stop within {grace_s}s; closing "
                     "system.wav anyway (its tail may be missing)")
        with self._wav_lock:
            if self._wav_file is not None:
                self._wav_file.close()  # patches the RIFF header shut
                self._wav_file = None

    def _capture_loop(self) -> None:
        try:
            self._do_capture()
        except Exception as exc:  # noqa: BLE001 - reported, never swallowed
            self.error = f"{type(exc).__name__}: {exc}"
            _log(f"system audio capture stopped: {self.error}")
        finally:
            self._started.set()

    def _write(self, mono_16k: np.ndarray) -> None:
        pcm = np.clip(mono_16k, -1.0, 1.0)
        with self._wav_lock:
            if self._wav_file is not None:
                self._wav_file.writeframes((pcm * 32767).astype(np.int16).tobytes())

    def _do_capture(self) -> None:
        with open_default_loopback() as recorder:
            self._started.set()  # device is open: start() may return
            errors = 0
            while not self._stop_event.is_set():
                try:
                    frames = recorder.record(CHUNK_FRAMES)
                except Exception as exc:  # noqa: BLE001
                    errors += 1
                    _log(f"read failed ({errors}/{MAX_CONSECUTIVE_ERRORS}): "
                         f"{type(exc).__name__}: {exc}")
                    if errors >= MAX_CONSECUTIVE_ERRORS:
                        raise RuntimeError(
                            f"loopback device failed {errors} times in a row"
                        ) from exc
                    continue
                errors = 0
                self._write(resample_to_16k(downmix_to_mono(frames),
                                            LOOPBACK_SAMPLE_RATE))
