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
            Ok(())
        }
        Some(win) => {
            // Window exists: apply size and position only if rect changed, then toggle visibility.
            // Never reposition while visible (forces unnecessary repaints).
            if let Some(r) = rect {
                let size = LogicalSize::new(r.w, r.h);
                let position = LogicalPosition::new(r.x, r.y);
                // Apply rect before showing to avoid flicker.
                let _ = win.set_inner_size(size);
                let _ = win.set_position(position);
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

#[cfg(not(windows))]
pub fn sync(_app: &tauri::AppHandle, _url: &str, _rect: Option<OrbRect>, _visible: bool) -> tauri::Result<()> {
    Ok(()) // macOS: laris hosts its own pyobjc overlay
}

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
