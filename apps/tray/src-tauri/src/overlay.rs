//! Transparent orb overlay window on Windows. The orb HTML/JS is served by
//! the laris FastAPI server (/overlay); here we host it in a click-through,
//! always-on-top, transparent Tauri window. On macOS laris drives its own
//! pyobjc window, so these functions are no-ops there.

use crate::laris::LarisPeer;

/// Position and size of the overlay in logical pixels (DIP), relative to the
/// monitor's top-left corner.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct OrbRect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

/// The overlay URL the window loads, carrying the auth token the orb JS needs
/// to open the /ws/voice websocket.
pub fn overlay_url(peer: &LarisPeer) -> String {
    format!("{}/overlay?token={}", peer.url, peer.token)
}

/// URL currently loaded in the orb window.
///
/// laris mints a fresh token on every boot (`secrets.token_hex(16)`), and saving
/// settings restarts the daemon. Without this the window kept the URL it was
/// created with, its token silently went stale, and /ws/voice refused every
/// reconnect - the orb stayed dead until the user toggled dictation off and on.
///
/// Tracked here rather than read back from `win.url()` because navigation is
/// asynchronous: `url()` still reports the old address right after `navigate()`,
/// which would make the next tick navigate again and reload the page.
#[cfg(windows)]
static LAST_URL: std::sync::Mutex<Option<String>> = std::sync::Mutex::new(None);

#[cfg(windows)]
fn remember_url(url: &str) {
    if let Ok(mut last) = LAST_URL.lock() {
        *last = Some(url.to_string());
    }
}

/// Rect currently applied to the orb window, so `sync` can be called on every
/// poll tick without re-issuing SetWindowPos. Repositioning a transparent
/// always-on-top window forces the compositor to repaint it, so doing it every
/// 2s for an unchanged rect is pure waste.
#[cfg(windows)]
static LAST_RECT: std::sync::Mutex<Option<OrbRect>> = std::sync::Mutex::new(None);

#[cfg(windows)]
pub fn sync(
    app: &tauri::AppHandle,
    url: &str,
    rect: Option<OrbRect>,
    visible: bool,
) -> tauri::Result<()> {
    use tauri::{LogicalPosition, LogicalSize, Manager, WebviewUrl, WebviewWindowBuilder};

    match app.get_webview_window("orb") {
        None => {
            // Window doesn't exist: create it with the rect, but start invisible.
            // The window is persistent and reused for every dictation session.
            let Some(r) = rect else {
                return Ok(()); // can't create without rect
            };
            let Ok(parsed) = url.parse::<tauri::Url>() else {
                return Ok(()); // malformed URL, skip
            };
            let size = LogicalSize::new(r.w, r.h);
            let position = LogicalPosition::new(r.x, r.y);
            let win = WebviewWindowBuilder::new(app, "orb", WebviewUrl::External(parsed))
                .transparent(true)
                .decorations(false)
                .always_on_top(true)
                .skip_taskbar(true)
                .focused(false)
                .resizable(false)
                .shadow(false)
                .inner_size(size.width, size.height)
                .position(position.x, position.y)
                .visible(false)
                .build()?;
            let _ = win.set_ignore_cursor_events(true);
            remember_url(url);
            if let Ok(mut last) = LAST_RECT.lock() {
                *last = Some(r);
            }
            Ok(())
        }
        Some(win) => {
            // The daemon may have restarted since this window was created, which
            // means a new token and therefore a new URL. Re-navigate before doing
            // anything else, otherwise we would show an orb whose websocket can
            // never authenticate.
            let stale = LAST_URL
                .lock()
                .map(|last| last.as_deref() != Some(url))
                .unwrap_or(false);
            if stale && !url.is_empty() {
                if let Ok(parsed) = url.parse::<tauri::Url>() {
                    let _ = win.navigate(parsed);
                    remember_url(url);
                }
            }

            // Apply size and position only when they actually changed - see LAST_RECT.
            // Always before show(), never while visible, to avoid flicker.
            if let Some(r) = rect {
                let changed = LAST_RECT.lock().map(|last| *last != Some(r)).unwrap_or(true);
                if changed {
                    let _ = win.set_inner_size(LogicalSize::new(r.w, r.h));
                    let _ = win.set_position(LogicalPosition::new(r.x, r.y));
                    if let Ok(mut last) = LAST_RECT.lock() {
                        *last = Some(r);
                    }
                }
            }
            if visible {
                let _ = win.show();
            } else {
                let _ = win.hide();
            }
            Ok(())
        }
    }
}

/// Destroy the orb window. Called when the engine dies: keeping a window alive
/// against a dead daemon leaves it reconnecting to nothing, and its URL carries
/// a token that will not exist after the next boot.
#[cfg(windows)]
pub fn close(app: &tauri::AppHandle) {
    use tauri::Manager;
    if let Some(win) = app.get_webview_window("orb") {
        let _ = win.close();
    }
    if let Ok(mut last) = LAST_URL.lock() {
        *last = None;
    }
}

#[cfg(not(windows))]
pub fn sync(_app: &tauri::AppHandle, _url: &str, _rect: Option<OrbRect>, _visible: bool) -> tauri::Result<()> {
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

    #[test]
    fn orb_rect_equality() {
        let r1 = OrbRect { x: 100.0, y: 200.0, w: 190.0, h: 190.0 };
        let r2 = OrbRect { x: 100.0, y: 200.0, w: 190.0, h: 190.0 };
        let r3 = OrbRect { x: 100.0, y: 200.0, w: 200.0, h: 190.0 };
        assert_eq!(r1, r2);
        assert_ne!(r1, r3);
    }
}
