"""Windows WASAPI loopback system audio capture (in-process, thread-based)."""
import threading
import wave
from pathlib import Path
from typing import Optional

import numpy as np

from miris.systemtap import Tap

# Loopback device sample rate (typical: 48 kHz)
LOOPBACK_SAMPLE_RATE = 48000
TARGET_SAMPLE_RATE = 16000


class WindowsLoopbackTap(Tap):
    """Capture system audio via WASAPI loopback in a background thread.

    - Reads from the default speaker's loopback (Stereo Mix / NVIDIA HiFi)
    - Downsamples 48kHz stereo -> 16kHz mono in-process (numpy polyphase)
    - Writes 16-bit PCM to out_wav incrementally
    - Thread-safe start/stop with clean WAV finalization
    """

    def __init__(self, out_wav: Path):
        self.out_wav = out_wav
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wav_file: Optional[wave.Wave_write] = None
        self._wav_lock = threading.Lock()

    def start(self) -> None:
        """Start loopback capture thread."""
        if self._thread is not None:
            raise RuntimeError("WindowsLoopbackTap already started")

        # Pre-allocate WAV file (will be updated as frames arrive)
        with self._wav_lock:
            self._wav_file = wave.open(str(self.out_wav), "wb")
            self._wav_file.setnchannels(1)  # mono
            self._wav_file.setsampwidth(2)  # 16-bit
            self._wav_file.setframerate(TARGET_SAMPLE_RATE)

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, daemon=False)
        self._thread.start()

    def alive(self) -> bool:
        """Check if capture thread is running."""
        return (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stop_event.is_set()
        )

    def stop(self, grace_s: float = 5.0) -> None:
        """Stop loopback capture and finalize WAV."""
        if self._thread is None:
            return

        # Signal thread to stop
        self._stop_event.set()

        # Wait for thread to finish (with timeout)
        self._thread.join(timeout=grace_s)
        if self._thread.is_alive():
            # Thread didn't stop in time; log warning but proceed with close
            import warnings
            warnings.warn(
                f"WindowsLoopbackTap capture thread did not stop within {grace_s}s; "
                "closing WAV anyway (may be incomplete)"
            )

        # Finalize and close WAV
        with self._wav_lock:
            if self._wav_file is not None:
                self._wav_file.close()
                self._wav_file = None

        self._thread = None

    def _capture_loop(self) -> None:
        """Capture audio frames from loopback and write to WAV.

        Runs in background thread; exits when _stop_event is set.
        """
        try:
            self._do_capture()
        except Exception as e:
            import warnings
            warnings.warn(f"WindowsLoopbackTap capture error: {e}")

    def _do_capture(self) -> None:
        """Inner capture loop with soundcard."""
        import soundcard as sc

        # Get default speaker's loopback
        speaker = sc.default_speaker()
        loopback = speaker.loopback

        # Parameters for loopback stream
        # Note: soundcard typically offers the device in its native format;
        # common formats: 48kHz stereo float32
        CHUNK_SIZE = 4800  # 100ms @ 48kHz

        try:
            with loopback.recorder(samplerate=LOOPBACK_SAMPLE_RATE) as recorder:
                while not self._stop_event.is_set():
                    try:
                        # Read chunk (may be stereo or mono depending on device)
                        data = recorder.record(CHUNK_SIZE)

                        # Ensure stereo; extract left channel if needed
                        if len(data.shape) == 1:
                            mono = data
                        else:
                            mono = data[:, 0] if data.shape[1] > 0 else data[:, 0]

                        # Downsample 48kHz -> 16kHz using decimation
                        # ratio = 48000 / 16000 = 3
                        decimation_factor = LOOPBACK_SAMPLE_RATE // TARGET_SAMPLE_RATE
                        resampled = self._resample_poly(
                            mono, 1, decimation_factor
                        )

                        # Write to WAV
                        with self._wav_lock:
                            if self._wav_file is not None:
                                pcm = np.clip(resampled, -1.0, 1.0)
                                self._wav_file.writeframes(
                                    (pcm * 32767).astype(np.int16).tobytes()
                                )
                    except Exception as e:
                        import warnings
                        warnings.warn(f"Error reading loopback frame: {e}")
                        if self._stop_event.is_set():
                            break
        except Exception as e:
            import warnings
            warnings.warn(f"Failed to open loopback: {e}")

    @staticmethod
    def _resample_poly(x: np.ndarray, up: int, down: int) -> np.ndarray:
        """Simple decimation resampling (downsample by taking every Nth sample).

        For soundcard's loopback (typically 48kHz -> 16kHz, down=3, up=1),
        we use simple decimation after a basic low-pass filter via moving average.
        This avoids scipy dependency while preventing aliasing.
        """
        # Simple low-pass via moving average (window size = down factor)
        # This is a first-order low-pass filter that reduces high frequencies
        kernel_size = down
        kernel = np.ones(kernel_size) / kernel_size
        # Pad to avoid edge artifacts
        x_padded = np.pad(x, (kernel_size // 2, kernel_size // 2), mode="edge")
        filtered = np.convolve(x_padded, kernel, mode="valid")

        # Decimate: take every Nth sample
        return filtered[::down]
