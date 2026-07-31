# MIRIS

Meeting Intelligence Recording & Insight System - local Krisp-style meeting
recorder for Windows (sibling of LARIS, in this same repository). Records both
sides of any call (mic + system audio via WASAPI loopback - Discord, Zoom,
Teams, Meet, anything the machine plays), transcribes locally with whisper.cpp
(pt-BR), then asks the configured LLM CLI (`agy` by default) for a summary,
action items and a category, and saves the note into the Obsidian vault folder
mapped to that category.

## Requirements

- Windows 10/11 x64
- [Antigravity CLI](https://antigravity.google) logged in (`agy`), or edit
  `llm_command` in the config to any prompt-in/text-out CLI

## Setup

```powershell
py -3.11 -m venv .venv
.venv\Scriptsctivate
pip install -r requirements.txt
miris doctor
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
