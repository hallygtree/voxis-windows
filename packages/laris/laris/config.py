"""Voice pipeline configuration."""
import os

from laris.settings import load_settings

_FILE_OVERRIDES = load_settings()


def _setting(key: str, default: str) -> str:
    return _FILE_OVERRIDES.get(key, os.environ.get(key, default))


MODE = _setting("ASSISTANT_MODE", "ptt")  # "ptt" | "always_on"
import sys as _sys
# cmd_r does not exist on Windows; right-shift is a comfortable PTT key there
# and is in hotkey.py's allowed set. Users change it in the tray settings.
_DEFAULT_DICTATE_KEY = "shift_r" if _sys.platform == "win32" else "cmd_r"
DICTATE_KEY = _setting("DICTATE_KEY", _DEFAULT_DICTATE_KEY)

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512               # Silero VAD window at 16 kHz
MIN_SPEECH_DURATION_MS = 400
MAX_SPEECH_DURATION_S = 30
VAD_THRESHOLD = 0.5
VAD_MIN_SILENCE_MS = 400

# The Windows engine bundle is torch-free (no DeepFilterNet), so denoise there
# degrades to passthrough and would warn once per utterance. Default it off on
# Windows; keep it on where torch is available. Env override wins either way.
_DEFAULT_NOISE_REDUCTION = "off" if _sys.platform == "win32" else "on"
NOISE_REDUCTION: str = _setting("NOISE_REDUCTION", _DEFAULT_NOISE_REDUCTION)  # "on" | "off"

# q4: benchmarked 2026-07-11 vs the f16 turbo - 0.76s vs 0.95s per utterance
# and ~1.2GB less resident RAM, transcription quality tied on pt-BR samples.
# Revert with STT_MODEL=mlx-community/whisper-large-v3-turbo if quality dips.
STT_MODEL: str = _setting("STT_MODEL", "mlx-community/whisper-large-v3-turbo-q4")
# whisper.cpp GGML model for the Windows/Linux backend (a file name, not the
# mlx repo id STT_MODEL holds). Downloaded on first use into
# ~/.config/voice-at/models. The turbo weights match what macOS runs
# (mlx-community/whisper-large-v3-turbo-q4): 4 decoder layers, ~8x faster
# decode than full large-v3, and the q5_0 quantization measured identical
# word-for-word to the unquantized output on pt-BR. Point this at another ggml
# file (name in the models dir, or an absolute path) to override.
STT_MODEL_GGML: str = _setting("STT_MODEL_GGML", "ggml-large-v3-turbo-q5_0.bin")
# empty string = Whisper auto-detect per utterance (used by miris for
# bilingual meetings); laris dictation keeps the pt-BR lock by default
STT_LANGUAGE: str = os.environ.get("STT_LANGUAGE", "pt")

ORB_THEME_PATH: str = os.environ.get(
    "ORB_THEME_PATH", "~/.config/voice-at/orb-theme.json"
)
