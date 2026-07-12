# LARIS

Local Audio Recognition & Input System - the mute transcriber core behind
[claude-code-ops](https://github.com/sammyjdev/claude-code-ops)'s voice
input: push-to-talk (hold a key) or hands-free (double-tap) dictation into
whatever app is focused, via local `mlx-whisper` STT. No TTS, no LLM - see
[KIRIS](https://github.com/sammyjdev/kiris) for the voice-assistant layer
built on top.

## Running standalone

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m laris
```

Standalone mode is dictation-only (no tmux session targeting - that needs a
`VoiceSession` wired to a real session backend, which is what
`claude-code-ops` does).

## Testing

```bash
pytest -q
```
