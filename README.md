<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/voxis-wordmark-dark.svg">
    <img src="brand/voxis-wordmark-light.svg" alt="VOXIS" width="360">
  </picture>
</p>

<p align="center">
  Local-first voice product family. The "O" is the orb - a circular waveform
  that lights up when VOXIS listens.
</p>

---

## Family

| Package | What |
|---------|------|
| `packages/laris` | Dictation engine - push-to-talk / hands-free local STT (mlx-whisper), desktop orb overlay, themeable (`/theme` API) |
| `packages/miris` | Meeting engine - records mic + system audio (Core Audio tap), transcribes locally, LLM summary + classification into the Obsidian vault |
| `apps/tray` | Tray app (Tauri v2) - record meetings, dictation toggles, orb theme, native settings window |
| `brand/` | Wordmark, mark and menu-bar variants (SVG) |

Each package keeps its own venv, tests and README - see inside.

## Install

Full steps per component and per OS: **[docs/INSTALL.md](docs/INSTALL.md)**.

Quick version (macOS, Apple Silicon):

```bash
git clone https://github.com/sammyjdev/voxis.git ~/code/voxis
# dictation
cd ~/code/voxis/packages/laris && python3.11 -m venv .venv && \
  .venv/bin/pip install -r requirements.txt && .venv/bin/python -m laris
# meetings
cd ~/code/voxis/packages/miris && python3.11 -m venv .venv && \
  .venv/bin/pip install -r requirements.txt -r ../laris/requirements.txt && \
  make -C helper && .venv/bin/miris doctor
```

The tray app installs from the
[Releases page](https://github.com/sammyjdev/voxis/releases) (unsigned - see
INSTALL.md for the one-time Gatekeeper/SmartScreen step).

**Windows / Linux**: the tray compiles and bundles there, but the engines are
macOS-only (mlx-whisper + Core Audio), so there is nothing to control yet.
Tray-side portability is deliberate; engine portability is the open work.

## Privacy & security

- **Local by default.** Audio, transcripts and notes never leave your machine
  except through the LLM CLI you configure for meeting summaries (`agy` by
  default) - that one call is the only outbound path, and you choose the tool.
- Session recordings and the auth token are written owner-only (`0600`).
- Dependencies are scanned continuously (cargo-audit + npm audit, see
  `.github/workflows/security-audit.yml`); 0 known vulnerabilities in the
  shipped tray.
- Releases are unsigned - see INSTALL.md.

## Status

- macOS-first today. The tray disables menu items when engines are absent
  or offline, never crashes.
- Meetings: two-channel recording ("Eu"/"Eles") gives speaker separation for
  free; notes route to the vault by user-defined categories.
- Panel (claude-code-ops) is fully decoupled since 2026-07-16.
