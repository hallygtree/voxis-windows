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
  Windows-focused functionality port of
  <a href="https://github.com/sammyjdev/voxis">sammyjdev/voxis</a> - same app,
  with the macOS-only engines (mlx-whisper, Core Audio) swapped for
  cross-platform equivalents so dictation and meetings run on Windows too.
</p>

---

## Family

| Package | What |
|---------|------|
| `packages/laris` | Dictation engine - push-to-talk / hands-free local STT, desktop orb overlay, themeable (`/theme` API). Runs on macOS and Windows. |
| `packages/miris` | Meeting engine - records mic + system audio, transcribes locally, LLM summary + classification into the Obsidian vault. Runs on macOS and Windows. |
| `apps/tray` | Tray app (Tauri v2) - record meetings, dictation toggles, orb theme, native settings window. |
| `brand/` | Wordmark, mark and menu-bar variants (SVG). |

Each package keeps its own venv, tests and README - see inside.

## Install

Full steps per component and per OS: **[docs/INSTALL.md](docs/INSTALL.md)**.

On **Windows**, the tray installer bundles both engines - no Python or Rust
needed. Download the latest build from this fork's
[Releases page](https://github.com/Allyhgf/voxis-windows/releases):
`VOXIS_x.y.z_x64_en-US.msi` (MSI, recommended) or
`VOXIS_x.y.z_x64-setup.exe` (NSIS). Builds are unsigned, so SmartScreen shows a
one-time "unknown publisher" prompt - choose **More info -> Run anyway**.

On **macOS**, use the upstream project:
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

- The Windows port is at **alpha** (`v0.1.0-alpha`): end-to-end dictation and
  meeting transcription work; UI parity with macOS and general polish are in
  progress.
- The tray disables menu items when engines are absent or offline, and never
  crashes.
- Meetings: two-channel recording ("Eu"/"Eles") gives speaker separation for
  free; notes route to the vault by user-defined categories.
- Linux: the tray compiles, but the engines are not ported yet.
