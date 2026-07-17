"""Cross-platform STT via faster-whisper (CTranslate2). The Windows/Linux
backend; macOS keeps mlx-whisper (transcriber.py). Device is chosen at
runtime: CUDA float16 when present, else CPU int8."""
from __future__ import annotations

import numpy as np

from faster_whisper import WhisperModel

from laris import config


def _cuda_available() -> bool:
    """True if a usable CUDA runtime is present. Best-effort: any failure
    (no driver, no NVIDIA GPU, ctranslate2 built CPU-only) means CPU."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 - absence of CUDA is the common case, not an error
        return False


class FasterWhisperTranscriber:
    def __init__(self) -> None:
        if _cuda_available():
            device, compute_type = "cuda", "float16"
        else:
            device, compute_type = "cpu", "int8"
        self._model = WhisperModel(
            config.STT_MODEL_FASTER, device=device, compute_type=compute_type
        )

    def warm(self) -> None:
        """Force model load + first inference so the first real utterance
        doesn't pay it."""
        self.transcribe(np.zeros(config.SAMPLE_RATE // 2, dtype=np.float32),
                        config.SAMPLE_RATE)

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
