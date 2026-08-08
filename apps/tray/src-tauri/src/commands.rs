//! Tauri commands backing the settings window.

use std::path::PathBuf;

use tauri::{AppHandle, Manager};

use crate::{laris, settings, AppState};

const KNOWN_LARIS_KEYS: [&str; 5] = [
    "ASSISTANT_MODE",
    "DICTATE_KEY",
    "STT_MODEL",
    "STT_MODEL_GGML",
    "NOISE_REDUCTION",
];

// mirror of laris/hotkey.py _ALLOWED
const DICTATE_KEYS: [&str; 15] = [
    "cmd_r", "cmd_l", "shift_r", "shift_l", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
    "f13", "f14", "f15",
];

/// Value-level validation: a select with no matching option submits "" - the
/// key check alone would happily persist it and break the engine at boot.
fn valid_value(key: &str, value: &serde_json::Value) -> bool {
    let Some(s) = value.as_str() else { return false };
    match key {
        "ASSISTANT_MODE" => matches!(s, "ptt" | "always_on"),
        "NOISE_REDUCTION" => matches!(s, "on" | "off"),
        "DICTATE_KEY" => DICTATE_KEYS.contains(&s),
        "STT_MODEL" => !s.trim().is_empty(),
        "STT_MODEL_GGML" => !s.trim().is_empty(),
        _ => false,
    }
}

#[derive(serde::Serialize)]
pub struct SettingsPayload {
    laris: serde_json::Map<String, serde_json::Value>,
    miris: serde_json::Value,
    theme: Option<serde_json::Value>,
    laris_alive: bool,
    version: String,
    /// The engine's platform, straight from the build that spawns it. The UI
    /// picks per-platform defaults (DICTATE_KEY, STT model key) from this;
    /// sniffing navigator.userAgent instead would put the whole thing at the
    /// mercy of a webview UA string, and getting it wrong is silent - the
    /// user saves a key that simply never fires.
    platform: String,
}

fn peer() -> Option<laris::LarisPeer> {
    laris::read_peer(&settings::config_dir().join("peers.json"))
}

#[tauri::command]
pub async fn get_settings(app: AppHandle) -> SettingsPayload {
    let state = app.state::<AppState>();
    let miris_toml = PathBuf::from(&state.config.miris_home).join("config.toml");
    let peer = peer();
    let laris_alive = peer.as_ref().map(|p| laris::alive(&p.url)).unwrap_or(false);
    let theme = peer
        .filter(|_| laris_alive)
        .and_then(|p| laris::get_theme(&p, None, None).ok())
        .and_then(|mut body| body.get_mut("theme").map(serde_json::Value::take));
    SettingsPayload {
        laris: settings::read_json_map(&settings::laris_settings_path()),
        miris: settings::read_miris_config(&miris_toml)
            .unwrap_or_else(|_| serde_json::json!({})),
        theme,
        laris_alive,
        version: app.package_info().version.to_string(),
        platform: std::env::consts::OS.to_string(), // "windows" | "macos" | "linux"
    }
}

#[tauri::command]
pub async fn save_laris_settings(
    app: AppHandle,
    updates: serde_json::Map<String, serde_json::Value>,
) -> Result<(), String> {
    if let Some(bad) = updates
        .keys()
        .find(|k| !KNOWN_LARIS_KEYS.contains(&k.as_str()))
    {
        return Err(format!("unknown setting: {bad}"));
    }
    if let Some((key, value)) = updates.iter().find(|(k, v)| !valid_value(k, v)) {
        return Err(format!("invalid value for {key}: {value}"));
    }
    let path = settings::laris_settings_path();
    let mut map = settings::read_json_map(&path);
    // The settings window submits every laris field on every save, so pressing
    // Save without touching anything used to restart the engine and re-pay the
    // whole model load. Every one of these keys is read at boot, so a real
    // change does need the restart - but an unchanged form does not.
    let changed: Vec<String> = updates
        .iter()
        // filter hands the closure a reference to the pair, so v is &&Value
        // here while map.get yields Option<&Value> - hence the deref
        .filter(|(k, v)| map.get(k.as_str()) != Some(*v))
        .map(|(k, _)| k.to_string())
        .collect();
    for (k, v) in updates {
        map.insert(k, v);
    }
    let mode = map
        .get("ASSISTANT_MODE")
        .and_then(|v| v.as_str())
        .unwrap_or("ptt")
        .to_string();
    settings::write_json_atomic(&path, &serde_json::Value::Object(map))?;
    // apply immediately when the tray owns the daemon (settings load at boot)
    if !changed.is_empty() {
        // ASSISTANT_MODE is the one key the running daemon can take live, and
        // the checkbox here is the same toggle as the tray's - restarting for
        // it looked like a crash. Any other key is still read only at boot.
        if changed.iter().all(|k| k == "ASSISTANT_MODE") {
            crate::apply_mode(&app, &mode);
        } else {
            let state = app.state::<AppState>();
            let mut daemon = state.daemon.lock().unwrap();
            if daemon.owns_running() {
                daemon.stop();
                daemon.spawn()?;
            }
        }
    }
    Ok(())
}

#[tauri::command]
pub async fn save_miris_config(
    app: AppHandle,
    vault_root: String,
    llm_command: Vec<String>,
    categories: Vec<(String, String)>,
) -> Result<(), String> {
    let state = app.state::<AppState>();
    let path = PathBuf::from(&state.config.miris_home).join("config.toml");
    settings::update_miris_config(&path, &vault_root, &llm_command, &categories)
}

#[tauri::command]
pub async fn save_theme(updates: serde_json::Value) -> Result<serde_json::Value, String> {
    let peer = peer().ok_or("laris offline")?;
    laris::set_theme(&peer, updates)
}

pub fn show_settings_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("settings") {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }
    // Shadowing rather than `let mut` + cfg block: on non-Windows the binding is
    // never reassigned, which warns.
    let builder = tauri::WebviewWindowBuilder::new(app, "settings", tauri::WebviewUrl::default())
        .title("VOXIS - Configurações")
        .inner_size(560.0, 680.0)
        .center()
        .min_inner_size(480.0, 520.0)
        .theme(None);

    // Runs before any script on the page, so the stylesheet can key off the
    // platform without the flash that an async load() would cause.
    #[cfg(windows)]
    let builder =
        builder.initialization_script("document.documentElement.classList.add('plat-windows');");

    let _ = builder.build();
}
