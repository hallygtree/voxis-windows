# VOXIS Tray

Cross-platform tray app (Tauri v2) - the control surface for LARIS
(dictation) and MIRIS (meeting recorder).

## Dev

    npm install
    npm run tauri dev

## Build installers

    npm run tauri build        # bundles under src-tauri/target/release/bundle/

Unsigned: macOS Gatekeeper requires right-click > Open on first launch.
Signing/notarization is documented as out of scope for v1.

## Config files

| File | Owner | Purpose |
|------|-------|---------|
| ~/.config/voice-at/tray.json | tray | absolute paths: miris_bin, laris_dir, miris_home |
| ~/.config/voice-at/laris-settings.json | tray | laris overrides (file > env > default), read at daemon start |
| ~/.config/voice-at/peers.json | laris | overlay URL + token (read-only for the tray) |
| ~/.miris/config.toml | user/tray | vault, categories, llm_command (comments preserved) |

Engines are not bundled: laris/miris stay macOS-only Python packages in
this monorepo; the tray disables their menu items when they are absent.
