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

**macOS (Apple Silicon)** - the only fully supported platform today:

1. Engines: clone the repo, create the venvs (`packages/*/README.md`),
   compile `packages/miris/helper` (`make`).
2. Tray: `cd apps/tray && npm install && npm run tauri build` - installs from
   `src-tauri/target/release/bundle/dmg/VOXIS_*.dmg`.

### Unsigned builds

Releases are not code-signed or notarized (no paid developer certificates).
What you will see:

- **macOS**: Gatekeeper blocks the app ("damaged" / "cannot be verified").
  After dragging VOXIS to Applications, clear the quarantine flag once:
  `xattr -cr /Applications/VOXIS.app`. On macOS 15+ a right-click > Open is
  no longer enough.
- **Windows**: SmartScreen shows "unknown publisher" - "More info" > "Run
  anyway".
- **Linux**: `.deb`/AppImage are unaffected.

**Windows / Linux**: the tray compiles and bundles (.msi/.deb/AppImage via
`tauri build`) but has nothing to control there yet - the engines depend on
mlx-whisper (Apple Silicon) and Core Audio. Tray-side portability is done on
purpose; engine portability is the open work.

## Status

- macOS-first today. The tray disables menu items when engines are absent
  or offline, never crashes.
- Meetings: two-channel recording ("Eu"/"Eles") gives speaker separation for
  free; notes route to the vault by user-defined categories.
- Panel (claude-code-ops) is fully decoupled since 2026-07-16.
