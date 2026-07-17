"""Voice pipeline configuration."""
import os

MODE = os.environ.get("ASSISTANT_MODE", "ptt")  # "ptt" | "always_on"
DICTATE_KEY = os.environ.get("DICTATE_KEY", "cmd_r")

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 512               # Silero VAD window at 16 kHz
MIN_SPEECH_DURATION_MS = 400
MAX_SPEECH_DURATION_S = 30
VAD_THRESHOLD = 0.5
VAD_MIN_SILENCE_MS = 400

NOISE_REDUCTION: str = os.environ.get("NOISE_REDUCTION", "on")  # "on" | "off"

# q4: benchmarked 2026-07-11 vs the f16 turbo - 0.76s vs 0.95s per utterance
# and ~1.2GB less resident RAM, transcription quality tied on pt-BR samples.
# Revert with STT_MODEL=mlx-community/whisper-large-v3-turbo if quality dips.
STT_MODEL: str = os.environ.get("STT_MODEL", "mlx-community/whisper-large-v3-turbo-q4")
# empty string = Whisper auto-detect per utterance (used by miris for
# bilingual meetings); laris dictation keeps the pt-BR lock by default
STT_LANGUAGE: str = os.environ.get("STT_LANGUAGE", "pt")

ORB_THEME_PATH: str = os.environ.get(
    "ORB_THEME_PATH", "~/.config/voice-at/orb-theme.json"
)
