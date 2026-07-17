# VOXIS

Local-first voice product family. The "O" is the orb - a circular waveform
that lights up when VOXIS listens.

| Package | What |
|---------|------|
| `packages/laris` | Dictation engine - push-to-talk / hands-free local STT (mlx-whisper), desktop orb overlay, themeable (`/theme` API) |
| `packages/miris` | Meeting engine - records mic + system audio (Core Audio tap), transcribes locally, LLM summary + classification into the Obsidian vault |
| `apps/tray` | Cross-platform tray app (Tauri v2) - MIRIS on/off at a glance, LARIS toggles, orb theme, native settings window |
| `brand/` | Wordmark and mark (SVG) |

Each package keeps its own venv, tests and README - see inside.

## Status

- macOS-first today (mlx-whisper needs Apple Silicon; the audio tap is Core Audio).
  The tray app is built portable (Windows/Linux/macOS) ahead of engine portability.
- Panel (claude-code-ops) is fully decoupled since 2026-07-16.
