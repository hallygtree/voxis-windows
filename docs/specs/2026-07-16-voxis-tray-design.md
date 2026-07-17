# VOXIS Tray - Design

**Date:** 2026-07-16
**Status:** Draft - awaiting user review
**Home:** `apps/tray` in the voxis monorepo

## What

Cross-platform (macOS/Windows/Linux) system-tray app - the unified face of
VOXIS. Tray icon = the VOXIS mark (brand/voxis-mark.svg) showing **MIRIS
recording state** (on/off). Native sober menu (style A, validated via mockups)
for quick actions; a native-feeling settings window for configuration.
Easy installation is a hard requirement: one small installer per OS.

## Decisions (validated with the user 2026-07-16)

| Decision | Choice | Why |
|----------|--------|-----|
| Stack | **Tauri v2** (Rust core + web UI) | "mais funcional, leve e portável possível": ~10MB native installers (.dmg/.msi/.deb/AppImage), first-class tray, built-in updater. The app is a thin controller - almost no logic lives in Rust |
| Visual style | A - native sober (mockup `menubar-estilos.html`) | UI is for configuration/control, not identity; HUD style B rejected for the app (identity lives in the orb) |
| Tray icon states | 2 only: idle / **MIRIS recording** | User's explicit simplification; dictation state stays on the orb |
| Settings surface | Native window (Tauri window, system-styled) | User rejected browser pages |
| Portability scope | UI portable now; engines stay macOS (mlx/Core Audio) until ported | Investment in the product's future, stated explicitly |

## Menu (style A content)

- **Gravar reuniao / Parar gravacao** + status line ("gravando ha 12min") - runs `miris start/stop`, state from the pidfile via `miris status`
- **Ultima nota** -> opens the note in the vault (OS default for .md)
- Toggles: **Ditado** (laris daemon up/down), **Hands-free**
- Submenu **Tema do orb**: archetype / palette / position presets -> `POST /theme` on :8421 (token from `~/.config/voice-at/peers.json`)
- **Configuracoes...** -> settings window
- **Sair**

## Settings window

Sections: Ditado (activation key capture, hands-free default, STT model,
noise reduction), Reunioes (vault root, category->folder table, llm_command),
Orb (archetype/palette/position/size - same API), Sobre (version, links).

## Backend prerequisite (packages/laris)

Settings that today are env vars (`DICTATE_KEY`, `STT_MODEL`,
`NOISE_REDUCTION`, `ASSISTANT_MODE`) gain a persisted file
`~/.config/voice-at/laris-settings.json` (same atomic-write pattern as
orb-theme.json) read by `laris/config.py` as override layer:
file > env > default. The tray edits the file; laris picks it up on next
daemon start (live reload out of scope for v1).

## Integration contracts (all existing)

- `miris` CLI on PATH (start/stop/status/retry) + `~/.miris/sessions/`
- `GET/POST /theme` on :8421 (laris overlay server)
- `~/.config/voice-at/peers.json` for the laris token
- Vault note paths printed by `miris stop` / found in the newest session dir

## Error handling

- Engines not installed/running -> menu items disabled with tooltip, never crash
- `miris start` failure -> native notification with stderr tail
- Missing peers.json/token -> orb submenu disabled ("laris offline")

## Testing

- Rust: unit tests for the thin glue (status parsing, config file IO)
- Web UI: none beyond type-checking (thin forms)
- Manual smoke matrix: tray icon states + each menu action on macOS (primary);
  Win/Linux smoke deferred until an engine story exists there
- `tauri build` producing installable artifacts on macOS is part of DoD

## Out of scope

- Engine portability (mlx/Core Audio), live-reload of laris settings,
  auto-start on login (v1.1), signing/notarization (needed for distribution
  beyond the user's machines - documented, not implemented)
