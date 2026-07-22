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
  Windows functionality port of
  <a href="https://github.com/sammyjdev/voxis">sammyjdev/voxis</a>.
</p>

---

## Family

| Package | What |
|---------|------|
| `packages/laris` | Dictation engine - push-to-talk / hands-free local STT, desktop orb overlay, themeable (`/theme` API). |
| `packages/miris` | Meeting engine - records mic + system audio (WASAPI loopback), transcribes locally, LLM summary + classification into the Obsidian vault. |
| `apps/tray` | Tray app (Tauri v2) - record meetings, dictation toggles, orb theme, native settings window. |
| `brand/` | Wordmark, mark and menu-bar variants (SVG). |

Each package keeps its own venv, tests and README - see inside.

## Install

The tray installer bundles both engines - no Python or Rust needed. Download the
latest build from the
[Releases page](https://github.com/Allyhgf/voxis-windows/releases):
`VOXIS_x.y.z_x64_en-US.msi` (MSI, recommended) or
`VOXIS_x.y.z_x64-setup.exe` (NSIS). Builds are unsigned, so SmartScreen shows a
one-time "unknown publisher" prompt - choose **More info -> Run anyway**.

Full per-component steps are in **[docs/INSTALL.md](docs/INSTALL.md)**.

## Privacy & security

- **Local by default.** Audio, transcripts and notes never leave your machine
  except through the LLM CLI you configure for meeting summaries (`agy` by
  default) - that one call is the only outbound path, and you choose the tool.
- Recordings, transcripts and the auth token stay under your local user profile.
- Dependencies are scanned continuously (cargo-audit + npm audit, see
  `.github/workflows/security-audit.yml`).
- Releases are unsigned - see INSTALL.md.

## Status

The port is at **alpha** (`v0.1.0-alpha`): end-to-end dictation and meeting
transcription work; UI parity and general polish are in progress. The tray
disables menu items when the engines are absent or offline. Meetings use
two-channel recording ("Eu"/"Eles") for free speaker separation, and route
notes to the vault by user-defined categories.
