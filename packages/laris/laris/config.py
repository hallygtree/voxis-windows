"""Voice pipeline configuration."""
import os

from laris.settings import load_settings

_FILE_OVERRIDES = load_settings()


def _setting(key: str, default: str) -> str:
    return _FILE_OVERRIDES.get(key, os.environ.get(key, default))


MODE = _setting("ASSISTANT_MODE", "ptt")  # "ptt" | "always_on"
# Right-shift: comfortable to hold, and in hotkey.py's allowed set. Users
# change it in the tray settings.
DICTATE_KEY = _setting("DICTATE_KEY", "shift_r")

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512               # Silero VAD window at 16 kHz
MIN_SPEECH_DURATION_MS = 400
MAX_SPEECH_DURATION_S = 30
VAD_THRESHOLD = 0.5
VAD_MIN_SILENCE_MS = 400

# whisper.cpp GGML model, downloaded on first use into
# ~/.config/voice-at/models. The turbo weights have 4 decoder layers, ~8x
# faster decode than full large-v3, and the q5_0 quantization measured
# identical word-for-word to the unquantized output on pt-BR. Point this at
# another ggml file (name in the models dir, or an absolute path) to override.
STT_MODEL_GGML: str = _setting("STT_MODEL_GGML", "ggml-large-v3-turbo-q5_0.bin")
# empty string = Whisper auto-detect per utterance (used by miris for
# bilingual meetings); laris dictation keeps the pt-BR lock by default
STT_LANGUAGE: str = os.environ.get("STT_LANGUAGE", "pt")

ORB_THEME_PATH: str = os.environ.get(
    "ORB_THEME_PATH", "~/.config/voice-at/orb-theme.json"
)
