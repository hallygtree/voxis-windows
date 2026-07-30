"""Windows/Linux STT via whisper.cpp. Replaces the faster-whisper backend,
whose engine (CTranslate2) has no Vulkan or ROCm support and so could only ever
be accelerated on NVIDIA - and only by shipping ~2 GB of CUDA DLLs.

Backend chain, best first:

1. **Whisper large-v3-turbo on Vulkan** - runs on NVIDIA, AMD, Intel and
   integrated graphics; the Vulkan loader ships with the GPU driver, so the
   whole GPU cost is a ~70 MB `ggml-vulkan.dll`.
2. **Parakeet TDT v3 on CPU** - only when there is no GPU *and* the caller
   accepts it. ~7x faster than Whisper on CPU, but it covers 25 European
   languages instead of ~99, misreads more often and punctuates worse, so it is
   a fallback and never a default.
3. **Whisper on CPU** - slow but correct, for languages Parakeet cannot serve
   and for callers that need segment timestamps.

Miris constructs this with `allow_parakeet=False`: meetings need `.start/.end`
per segment, which only the Whisper path produces, and they are processed
offline where slowness is tolerable. Dictation is interactive and takes the
fast fallback.
"""
from __future__ import annotations

import io
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from laris import config
from laris import whispercpp_runtime as runtime


@dataclass(frozen=True)
class Segment:
    """miris.transcribe.transcribe_channel consumes these by .start / .end /
    .text - the contract that makes it prefer this over the torch+silero
    path, which is excluded from the Windows bundle."""
    start: float
    end: float
    text: str


def _wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """float32 [-1, 1] -> 16-bit PCM WAV in memory. Kept off disk: this is the
    user's voice, and the app's whole premise is that it never leaves the
    machine."""
    pcm = (np.clip(audio.astype(np.float32), -1.0, 1.0) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class WhisperCppTranscriber:
    def __init__(self, allow_parakeet: bool = True) -> None:
        self.backend = "unavailable"
        self.device = "none"
        self._server: runtime.WhisperServer | None = None
        self._parakeet_model: Path | None = None
        self._reported_unavailable = False

        for attempt in self._candidates(allow_parakeet):
            try:
                attempt()
                return
            except Exception as exc:  # noqa: BLE001 - try the next rung
                print(f"[STT] {self.backend} unavailable ({exc}); trying next backend")
                self._shutdown()
        # Deliberately not raising: the engine is packaged windowed, so an
        # exception here kills it with no window, no stderr and no popup - the
        # user just sees a dead tray. Booting degraded keeps the hotkey, the
        # orb and the log alive so the failure is diagnosable.
        self.backend = "unavailable"
        print("[STT] no usable backend; dictation will return nothing. "
              "Check that the whisper.cpp binaries shipped and that a model "
              "could be downloaded.")

    def _candidates(self, allow_parakeet: bool):
        device = runtime.best_device(runtime.vulkan_devices())
        if device is not None:
            yield lambda: self._start_whisper(device)
        if allow_parakeet and (config.STT_LANGUAGE or "en") in runtime.PARAKEET_LANGUAGES:
            yield self._start_parakeet
        yield lambda: self._start_whisper(None)

    def _start_whisper(self, device: runtime.VulkanDevice | None) -> None:
        self.backend = "whisper"
        self.device = f"vulkan:{device.index} ({device.name})" if device else "cpu"
        model = runtime.resolve_whisper_model(config.STT_MODEL_GGML)
        server = runtime.WhisperServer(model, device, config.STT_LANGUAGE)
        server.start()
        self._server = server
        print(f"[STT] whisper.cpp large-v3-turbo on {self.device}")

    def _start_parakeet(self) -> None:
        self.backend = "parakeet"
        self.device = "cpu"
        self._parakeet_model = runtime.ensure_model(runtime.PARAKEET_MODEL)
        print("[STT] no GPU found; using Parakeet TDT v3 on cpu (faster than "
              "Whisper on cpu, but 25 languages and weaker punctuation)")

    def warm(self) -> None:
        """Absorbs model load and, on the very first launch, Vulkan pipeline
        compilation (~25s measured; the driver caches it, so later launches are
        under a second). Never raises: daemon.run calls it unguarded."""
        try:
            self.transcribe(np.zeros(config.SAMPLE_RATE // 2, dtype=np.float32))
        except Exception as exc:  # noqa: BLE001
            print(f"[STT] warm-up failed ({exc}); continuing")

    def transcribe(self, audio: np.ndarray, sample_rate: int = config.SAMPLE_RATE) -> str:
        if len(audio) == 0:
            return ""
        if self.backend == "whisper" and self._server is not None:
            return str(self._server.infer(_wav_bytes(audio, sample_rate), False)
                       .get("text", "")).strip()
        if self.backend == "parakeet" and self._parakeet_model is not None:
            # strip here too, not only in the runtime helper: this text is typed
            # straight into whatever the user has focused, and a stray leading
            # space is a visible defect.
            return self._parakeet(audio, sample_rate).strip()
        self._report_unavailable()
        return ""

    def transcribe_with_vad(self, audio: np.ndarray,
                            sample_rate: int = config.SAMPLE_RATE) -> list:
        """Segments with timestamps, for miris. Only the Whisper path can
        produce these, which is why miris passes allow_parakeet=False."""
        if len(audio) == 0:
            return []
        if self.backend != "whisper" or self._server is None:
            self._report_unavailable()
            return []
        payload = self._server.infer(_wav_bytes(audio, sample_rate), True)
        return [
            Segment(float(s.get("start", 0.0)), float(s.get("end", 0.0)),
                    str(s.get("text", "")))
            for s in payload.get("segments", [])
            if str(s.get("text", "")).strip()
        ]

    def _parakeet(self, audio: np.ndarray, sample_rate: int) -> str:
        """parakeet-cli reads a file, so this one path does touch the disk.
        Written to the OS temp dir and deleted immediately."""
        tmp = Path(tempfile.gettempdir()) / f"voxis-{id(self)}.wav"
        try:
            tmp.write_bytes(_wav_bytes(audio, sample_rate))
            return runtime.parakeet_transcribe(self._parakeet_model, tmp)
        finally:
            tmp.unlink(missing_ok=True)

    def _report_unavailable(self) -> None:
        if not self._reported_unavailable:
            self._reported_unavailable = True
            print("[STT] transcription requested but no backend is available")

    def _shutdown(self) -> None:
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._parakeet_model = None

    def close(self) -> None:
        self._shutdown()
