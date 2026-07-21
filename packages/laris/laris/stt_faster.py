"""Cross-platform STT via faster-whisper (CTranslate2). The Windows/Linux
backend; macOS keeps mlx-whisper (transcriber.py). Device is chosen at
runtime: CUDA float16 when present, else CPU int8."""
from __future__ import annotations

import numpy as np

from faster_whisper import WhisperModel

from laris import config


def _cuda_available() -> bool:
    """True if ctranslate2 enumerates a CUDA device. NOT proof that CUDA
    works: the NVIDIA driver alone is enough to make this return 1, while
    ctranslate2 additionally needs cuBLAS/cuDNN, which are not bundled and
    not installed by pip on Windows. Validated for real by _probe()."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 - absence of CUDA is the common case, not an error
        return False


class FasterWhisperTranscriber:
    """CPU int8 is the guaranteed baseline (see docs/INSTALL.md); CUDA is
    used only when a probe inference actually succeeds on it."""

    def __init__(self) -> None:
        if _cuda_available():
            try:
                self._model = WhisperModel(
                    config.STT_MODEL_FASTER, device="cuda", compute_type="float16"
                )
                # A CUDA device being *enumerated* does not mean ctranslate2 can
                # run on it: with the driver present but cuBLAS/cuDNN missing,
                # the model builds fine and only the first encode() raises
                # ("Library cublas64_12.dll is not found"). That happened at
                # backend.warm() during daemon boot, killing the windowed engine
                # before the hotkey listener ever started - dictation just looked
                # dead. Force the kernel here so the failure is recoverable.
                self._probe()
                self.device, self.compute_type = "cuda", "float16"
                return
            except Exception as exc:  # noqa: BLE001 - any CUDA failure means CPU
                print(
                    f"[STT] CUDA device detected but unusable ({exc}); falling "
                    "back to CPU int8. Install the CUDA 12 CTranslate2 runtime "
                    "(cuBLAS + cuDNN 9) if you want GPU transcription."
                )
        self.device, self.compute_type = "cpu", "int8"
        self._model = WhisperModel(
            config.STT_MODEL_FASTER, device=self.device, compute_type=self.compute_type
        )

    def _probe(self) -> None:
        """Run one real inference. faster-whisper's transcribe() is lazy - the
        generator must be consumed or no kernel is ever launched."""
        self.transcribe(np.zeros(config.SAMPLE_RATE // 2, dtype=np.float32),
                        config.SAMPLE_RATE)

    def warm(self) -> None:
        """Force model load + first inference so the first real utterance
        doesn't pay it."""
        self._probe()

    def transcribe(self, audio: np.ndarray, sample_rate: int = config.SAMPLE_RATE) -> str:
        if len(audio) == 0:
            return ""
        segments, _info = self._model.transcribe(
            audio.astype(np.float32),
            language=config.STT_LANGUAGE or None,  # "" -> auto-detect
            task="transcribe",
            condition_on_previous_text=False,  # same anti-repetition fix as mlx path
        )
        return "".join(seg.text for seg in segments).strip()

    def transcribe_with_vad(self, audio: np.ndarray, sample_rate: int = config.SAMPLE_RATE) -> list:
        """Transcribe with VAD filtering enabled, returning segments with timestamps.
        Each segment has: start (seconds), end (seconds), text."""
        if len(audio) == 0:
            return []
        segments, _info = self._model.transcribe(
            audio.astype(np.float32),
            language=config.STT_LANGUAGE or None,  # "" -> auto-detect
            task="transcribe",
            condition_on_previous_text=False,
            vad_filter=True,  # Enable Silero VAD filtering
        )
        return list(segments)
