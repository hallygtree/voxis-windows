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

<p align="center">
  <strong>Windows port</strong> of
  <a href="https://github.com/sammyjdev/voxis">sammyjdev/voxis</a>.
</p>

---

## What this fork is

[VOXIS](https://github.com/sammyjdev/voxis) is a macOS-native voice product by
[@sammyjdev](https://github.com/sammyjdev). This repository ports it to
**Windows**, aiming for feature parity: dictation and meeting transcription that
work as well as they do on the Mac.

The macOS build depends on Apple-only pieces - `mlx-whisper` for speech-to-text
and a Core Audio tap for system audio. The port replaces those with
cross-platform equivalents (a torch-free `faster-whisper` STT and WASAPI
loopback capture) while keeping the same tray app, orb overlay, settings and
`/theme` API. Where behaviour must differ per platform it is guarded, so the
macOS path stays intact.

Upstream is credited as the origin of the design and most of the codebase; this
fork owns the Windows-specific engine backends, packaging and tray glue.

## Family

| Package | What |
|---------|------|
| `packages/laris` | Dictation engine - push-to-talk / hands-free local STT, desktop orb overlay, themeable (`/theme` API). Runs on macOS and Windows. |
| `packages/miris` | Meeting engine - records mic + system audio, transcribes locally, LLM summary + classification into the Obsidian vault. Runs on macOS and Windows. |
| `apps/tray` | Tray app (Tauri v2) - record meetings, dictation toggles, orb theme, native settings window. |
| `brand/` | Wordmark, mark and menu-bar variants (SVG). |

Each package keeps its own venv, tests and README - see inside.

## Install (Windows)

The tray installer bundles both engines - no Python or Rust needed to run the
app. Download the latest build from this fork's
[Releases page](https://github.com/Allyhgf/voxis-windows/releases):

- `VOXIS_x.y.z_x64_en-US.msi` - MSI installer (recommended)
- `VOXIS_x.y.z_x64-setup.exe` - NSIS installer

Builds are unsigned, so Windows SmartScreen shows a one-time "unknown publisher"
prompt - choose **More info -> Run anyway**. Full per-component steps and the
macOS instructions are in **[docs/INSTALL.md](docs/INSTALL.md)**.

> **Alpha.** This is an early build. Dictation and meetings work; UI polish and
> the last parity items are still landing. Expect rough edges and please report
> what breaks.

For **macOS**, use the upstream project:
[sammyjdev/voxis](https://github.com/sammyjdev/voxis).

## Privacy & security

- **Local by default.** Audio, transcripts and notes never leave your machine
  except through the LLM CLI you configure for meeting summaries (`agy` by
  default) - that one call is the only outbound path, and you choose the tool.
- Session recordings and the auth token are written owner-only.
- Dependencies are scanned continuously (cargo-audit + npm audit, see
  `.github/workflows/security-audit.yml`).
- Releases are unsigned - see INSTALL.md.

## Status

- **macOS and Windows both run dictation and meetings.** The Windows port is at
  **alpha** (`v0.1.0-alpha`): end-to-end dictation and meeting transcription
  work; UI parity with macOS and general polish are in progress.
- The tray disables menu items when engines are absent or offline, and never
  crashes.
- Meetings: two-channel recording ("Eu"/"Eles") gives speaker separation for
  free; notes route to the vault by user-defined categories.
- Linux: the tray compiles, but the engines are not ported yet.

## Relationship to upstream

This fork is developed independently and will be offered back to
[sammyjdev/voxis](https://github.com/sammyjdev/voxis) once Windows parity is
confirmed. It is not a substitute for the upstream project on macOS.
