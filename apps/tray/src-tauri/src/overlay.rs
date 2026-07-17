//! Transparent orb overlay window on Windows. The orb HTML/JS is served by
//! the laris FastAPI server (/overlay); here we host it in a click-through,
//! always-on-top, transparent Tauri window. On macOS laris drives its own
//! pyobjc window, so these functions are no-ops there.

use crate::laris::LarisPeer;

/// The overlay URL the window loads, carrying the auth token the orb JS needs
/// to open the /ws/voice websocket.
pub fn overlay_url(peer: &LarisPeer) -> String {
    format!("{}/overlay?token={}", peer.url, peer.token)
}

#[cfg(windows)]
pub fn open(app: &tauri::AppHandle, url: &str) -> tauri::Result<()> {
    use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

    if app.get_webview_window("orb").is_some() {
        return Ok(());
    }
    // parse fallibly: this runs on the poll thread, so a malformed peer URL
    // must skip the window, never panic the loop
    let Ok(parsed) = url.parse::<tauri::Url>() else {
        return Ok(());
    };
    let win = WebviewWindowBuilder::new(app, "orb", WebviewUrl::External(parsed))
        .transparent(true)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(false)
        .resizable(false)
        .shadow(false)
        .build()?;
    let _ = win.set_ignore_cursor_events(true);
    Ok(())
}

#[cfg(windows)]
pub fn close(app: &tauri::AppHandle) {
    use tauri::Manager;
    if let Some(win) = app.get_webview_window("orb") {
        let _ = win.close();
    }
}

#[cfg(not(windows))]
pub fn open(_app: &tauri::AppHandle, _url: &str) -> tauri::Result<()> {
    Ok(()) // macOS: laris hosts its own pyobjc overlay
}

#[cfg(not(windows))]
pub fn close(_app: &tauri::AppHandle) {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::laris::LarisPeer;

    #[test]
    fn overlay_url_carries_token() {
        let peer = LarisPeer { url: "http://127.0.0.1:8421".into(), token: "abc".into() };
        assert_eq!(overlay_url(&peer), "http://127.0.0.1:8421/overlay?token=abc");
    }
}
