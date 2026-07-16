# MIRIS

Meeting Intelligence Recording & Insight System - local Krisp-style meeting
recorder for macOS (sibling of [LARIS](https://github.com/sammyjdev/laris)).
Records both sides of any call (mic + system audio via a Core Audio process
tap - Discord, Zoom, Teams, Meet, anything the Mac plays), transcribes
locally with mlx-whisper (pt-BR), then asks the configured LLM CLI (`agy`
by default) for a summary, action items and a category, and saves the note
into the Obsidian vault folder mapped to that category.

## Requirements

- macOS 14.2+ (Core Audio process tap), Apple Silicon (mlx-whisper)
- Xcode CLT (`swiftc`) to build the audio helper
- [Antigravity CLI](https://antigravity.google) logged in (`agy`), or edit
  `llm_command` in the config to any prompt-in/text-out CLI

## Setup

```bash
git clone git@github.com:sammyjdev/laris.git ~/code/laris   # sibling dep
cd ~/code/miris
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r ../laris/requirements.txt
make -C helper          # builds helper/audiotap
miris doctor            # triggers the System Audio Recording permission prompt
```

## Use

```bash
miris start     # begin recording (detached; survives closing the terminal)
miris status
miris stop      # stop, transcribe, summarize, save note to the vault
miris retry <session-id>   # re-run summary/classification for a session
```

Config: `~/.miris/config.toml` (created on first run) - vault root, category
-> folder map, `llm_command`. Raw WAVs stay in `~/.miris/sessions/<ts>/`
until you delete them.

Known behavior: without a headset, the mic channel also hears the speakers,
so "Eu" may echo what "Eles" said. Use a headset for clean diarization.

## Testing

```bash
pytest -q
```
