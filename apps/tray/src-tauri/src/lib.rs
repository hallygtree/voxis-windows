mod commands;
mod laris;
mod miris;
mod overlay;
mod settings;

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::Duration;

use tauri::menu::{CheckMenuItem, IsMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::{TrayIcon, TrayIconBuilder};
use tauri::{AppHandle, Manager, Wry};
use tauri_plugin_notification::NotificationExt;

const ARCHETYPES: [&str; 3] = ["waveform", "reactor", "faceted"];
const PALETTES: [&str; 4] = ["blade", "noir", "acid", "ember"];
const POSITIONS: [&str; 6] = [
    "center", "top-left", "top-center", "top-right", "bottom-left", "bottom-right",
];

/// What the engine is doing while it boots. Text and fraction travel together
/// so the menu label and the bar can never disagree.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct BootStatus {
    pub text: Option<String>,
    pub progress: Option<f64>,
}

pub struct AppState {
    pub config: settings::TrayConfig,
    pub daemon: Mutex<laris::LarisDaemon>,
    pub processing: AtomicBool,
    /// Set on every menu click: native check items auto-toggle visually even
    /// when the action fails, so the next poll tick must rebuild regardless
    /// of whether the snapshot changed.
    pub menu_dirty: AtomicBool,
    /// Last known orb rect, updated by the 2s poll thread and read by the
    /// long-poll thread to avoid redundant GET /theme calls.
    pub last_orb_rect: Mutex<Option<overlay::OrbRect>>,
    /// Whether laris finished backend.warm() and the hotkey actually responds.
    /// Published by the long-poll thread from /overlay/state, read by
    /// take_snapshot: uvicorn answers well before the model is loaded, so
    /// `laris_alive` alone would tell the user dictation is ready too early.
    pub orb_ready: AtomicBool,
    /// Boot progress published by the long-poll thread, rendered in the
    /// dictation menu label and the tray tooltip while the engine is not
    /// ready. A 547 MB download with no visible sign of life reads as a hung
    /// app.
    pub boot_status: Mutex<BootStatus>,
}

#[derive(Debug, Clone, PartialEq, Default)]
struct Snapshot {
    recording: Option<(String, i64)>, // (session id, minutes)
    processing: bool,
    laris_alive: bool,
    ready: bool, // backend.warm() completed, model loaded, dictation key responds
    hands_free: bool,
    has_last_note: bool,
    theme: Option<(String, String, String)>, // (archetype, palette, position)
    rect: Option<overlay::OrbRect>, // position and size in logical pixels
    boot_status: BootStatus, // what the engine is doing while !ready
}

fn peers_path() -> PathBuf {
    settings::config_dir().join("peers.json")
}

fn sessions_dir(state: &AppState) -> PathBuf {
    PathBuf::from(&state.config.miris_home).join("sessions")
}

fn take_snapshot(app: &tauri::AppHandle, state: &AppState) -> Snapshot {
    let sessions = sessions_dir(state);
    let recording = match miris::status(&sessions) {
        miris::MirisStatus::Recording { session, .. } => {
            let mins = miris::recording_minutes(&session, chrono::Local::now()).unwrap_or(0);
            Some((session, mins))
        }
        miris::MirisStatus::Idle => None,
    };
    let peer = laris::read_peer(&peers_path());
    let laris_alive = peer.as_ref().map(|p| laris::alive(&p.url)).unwrap_or(false);

    // Screen geometry for the orb rect, in LOGICAL pixels (SDD-C0 §6): laris
    // computes the rect against whatever dimensions we send, and applying a rect
    // derived from physical pixels would misplace the orb on any display that is
    // not at 100% scaling.
    //
    // work_area() rather than size(): it excludes the taskbar, so a "bottom-*"
    // position lands above it instead of behind it. It does exist in tauri 2.11.5
    // (an earlier comment here claimed otherwise without checking).
    #[cfg(windows)]
    let (screen_w, screen_h, monitor_origin) = {
        app.primary_monitor()
            .ok()
            .flatten()
            .map(|m| {
                let scale = m.scale_factor();
                let area = m.work_area();
                let size = area.size.to_logical::<f64>(scale);
                let pos = area.position.to_logical::<f64>(scale);
                (size.width, size.height, (pos.x, pos.y))
            })
            .unwrap_or((1920.0, 1080.0, (0.0, 0.0)))
    };

    #[cfg(not(windows))]
    let (screen_w, screen_h, monitor_origin) = {
        let _ = app; // macOS positions its own pyobjc panel; nothing to measure here
        (1920.0, 1080.0, (0.0, 0.0))
    };

    // ponytail: theme fetched every tick while laris is up - localhost HTTP,
    // negligible; cache only if it ever shows up in a profile
    // `ready` does NOT come from /theme - that endpoint never returned it, so
    // reading it here left it permanently false and the tray menu stuck on
    // "carregando modelo...". It belongs to /overlay/state (SDD-C0 §16), which
    // the long-poll thread owns; it publishes the value here.
    let ready = state.orb_ready.load(Ordering::SeqCst);

    let (theme, rect) = peer
        .filter(|_| laris_alive)
        .and_then(|p| {
            laris::get_theme(&p, Some(screen_w), Some(screen_h)).ok().and_then(|body| {
                let t = body.get("theme")?;
                let theme_tuple = (
                    t.get("archetype")?.as_str()?.to_owned(),
                    t.get("palette")?.as_str()?.to_owned(),
                    t.get("position")?.as_str()?.to_owned(),
                );
                let rect = body.get("rect").and_then(|r| {
                    let x = r.get("x")?.as_f64()?;
                    let y = r.get("y")?.as_f64()?;
                    let w = r.get("w")?.as_f64()?;
                    let h = r.get("h")?.as_f64()?;
                    Some(overlay::OrbRect {
                        x: monitor_origin.0 + x,
                        y: monitor_origin.1 + y,
                        w,
                        h,
                    })
                });
                Some((Some(theme_tuple), rect))
            })
        })
        .unwrap_or_default();

    let laris_settings = settings::read_json_map(&settings::laris_settings_path());
    let hands_free =
        laris_settings.get("ASSISTANT_MODE").and_then(|v| v.as_str()) == Some("always_on");
    Snapshot {
        recording,
        processing: state.processing.load(Ordering::SeqCst),
        laris_alive,
        ready,
        hands_free,
        has_last_note: miris::last_note(&sessions).is_some(),
        theme,
        rect,
        // Owned by the long-poll thread, same as `ready` above.
        boot_status: state.boot_status.lock().map(|s| s.clone()).unwrap_or_default(),
    }
}

/// `0.43` -> `████░░░░░░ 43%`. A native menu item is text, so the "bar" is
/// block characters; there is no progress widget to use.
fn progress_bar(fraction: f64) -> String {
    const CELLS: usize = 10;
    let clamped = fraction.clamp(0.0, 1.0);
    let filled = (clamped * CELLS as f64).round() as usize;
    format!(
        "{}{} {:.0}%",
        "\u{2588}".repeat(filled),
        "\u{2591}".repeat(CELLS - filled),
        clamped * 100.0
    )
}

/// Hover text for the tray icon. This is the only place boot progress is
/// visible without opening the menu - and a menu that is already open does not
/// repaint, so it is where the live value actually lands.
fn tray_tooltip(snap: &Snapshot) -> String {
    if snap.laris_alive && !snap.ready {
        if let Some(text) = snap.boot_status.text.as_deref() {
            return match snap.boot_status.progress {
                Some(p) => format!("VOXIS - {text}\n{}", progress_bar(p)),
                None => format!("VOXIS - {text}"),
            };
        }
        return "VOXIS - carregando modelo...".to_string();
    }
    if snap.recording.is_some() {
        return "VOXIS - reuniao em andamento".to_string();
    }
    "VOXIS".to_string()
}

fn build_menu(app: &AppHandle, snap: &Snapshot) -> tauri::Result<Menu<Wry>> {
    let meeting = if snap.processing {
        MenuItem::with_id(app, "noop", "Processando reunião...", false, None::<&str>)?
    } else if let Some((_, mins)) = &snap.recording {
        MenuItem::with_id(app, "miris_stop", format!("Parar gravação ({mins} min)"), true, None::<&str>)?
    } else {
        MenuItem::with_id(app, "miris_start", "Gravar reunião", true, None::<&str>)?
    };
    let last_note =
        MenuItem::with_id(app, "last_note", "Última nota", snap.has_last_note, None::<&str>)?;
    let dictation_label = if snap.laris_alive && !snap.ready {
        // The engine reports what it is actually doing - downloading the model,
        // loading it, compiling GPU shaders. Falls back to the generic wording
        // when it has not said anything yet, or when it is an older engine that
        // does not report at all.
        match (snap.boot_status.text.as_deref(), snap.boot_status.progress) {
            (Some(status), Some(p)) if !status.is_empty() => {
                format!("Ditado {} - {status}", progress_bar(p))
            }
            (Some(status), None) if !status.is_empty() => format!("Ditado ({status})"),
            _ => "Ditado (carregando modelo…)".to_string(),
        }
    } else {
        "Ditado".to_string()
    };
    let dictation =
        CheckMenuItem::with_id(app, "dictation", &dictation_label, true, snap.laris_alive, None::<&str>)?;
    let hands_free = CheckMenuItem::with_id(
        // The checkbox permits the gesture; the double-tap is what starts a
        // session. Saying so here is the only place a user learns it.
        app, "hands_free", "Hands-free (duplo-toque na tecla)", snap.laris_alive,
        snap.hands_free, None::<&str>,
    )?;

    let (cur_arch, cur_pal, cur_pos) = snap.theme.clone().unwrap_or_default();
    let mut theme_children: Vec<Box<dyn IsMenuItem<Wry>>> = Vec::new();
    for a in ARCHETYPES {
        theme_children.push(Box::new(CheckMenuItem::with_id(
            app, format!("theme:archetype:{a}"), a, true, a == cur_arch, None::<&str>,
        )?));
    }
    theme_children.push(Box::new(PredefinedMenuItem::separator(app)?));
    for p in PALETTES {
        theme_children.push(Box::new(CheckMenuItem::with_id(
            app, format!("theme:palette:{p}"), p, true, p == cur_pal, None::<&str>,
        )?));
    }
    theme_children.push(Box::new(PredefinedMenuItem::separator(app)?));
    for p in POSITIONS {
        theme_children.push(Box::new(CheckMenuItem::with_id(
            app, format!("theme:position:{p}"), p, true, p == cur_pos, None::<&str>,
        )?));
    }
    let refs: Vec<&dyn IsMenuItem<Wry>> = theme_children.iter().map(|b| b.as_ref()).collect();
    let theme_menu =
        Submenu::with_id_and_items(app, "theme", "Tema do orb", snap.laris_alive, &refs)?;

    let settings_item =
        MenuItem::with_id(app, "settings", "Configurações...", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Sair", true, None::<&str>)?;
    let sep1 = PredefinedMenuItem::separator(app)?;
    let sep2 = PredefinedMenuItem::separator(app)?;
    Menu::with_items(app, &[
        &meeting, &last_note, &sep1, &dictation, &hands_free, &theme_menu, &sep2,
        &settings_item, &quit,
    ])
}

fn set_tray_icon(tray: &TrayIcon, recording: bool) {
    let bytes: &[u8] = if recording {
        include_bytes!("../icons/tray-rec.png")
    } else {
        include_bytes!("../icons/tray-idle.png")
    };
    if let Ok(img) = tauri::image::Image::from_bytes(bytes) {
        let _ = tray.set_icon(Some(img));
        // icon_as_template is macOS-only: it makes the icon adapt to theme
        // (light/dark). On Windows it's a no-op; the icon is already colored.
        #[cfg(target_os = "macos")]
        {
            let template = !recording;
            let _ = tray.set_icon_as_template(template);
        }
    }
}

fn notify(app: &AppHandle, body: &str) {
    let _ = app.notification().builder().title("VOXIS").body(body).show();
}

fn handle_menu(app: &AppHandle, id: &str) {
    let state = app.state::<AppState>();
    state.menu_dirty.store(true, Ordering::SeqCst);
    match id {
        "quit" => {
            state.daemon.lock().unwrap().stop();
            app.exit(0);
        }
        "settings" => commands::show_settings_window(app),
        "miris_start" => {
            // off the menu thread: the miris CLI takes seconds just to import
            let app2 = app.clone();
            let bin = state.config.miris_bin.clone();
            std::thread::spawn(move || {
                if let Err(e) = miris::start(&bin) {
                    notify(&app2, &format!("Falha ao iniciar gravação: {e}"));
                }
            });
        }
        "miris_stop" => {
            // the menu item only disables on the next poll tick - a double
            // click must not launch two concurrent `miris stop` pipelines
            if state
                .processing
                .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
                .is_err()
            {
                return;
            }
            let app2 = app.clone();
            let bin = state.config.miris_bin.clone();
            std::thread::spawn(move || {
                let msg = match miris::stop(&bin) {
                    Ok(note) => format!(
                        "Nota salva: {}",
                        note.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()
                    ),
                    Err(e) => format!("Falha ao processar reunião: {e}"),
                };
                app2.state::<AppState>().processing.store(false, Ordering::SeqCst);
                notify(&app2, &msg);
            });
        }
        "last_note" => {
            if let Some(note) = miris::last_note(&sessions_dir(&state)) {
                let _ = tauri_plugin_opener::open_path(note, None::<&str>);
            }
        }
        "dictation" => {
            // off the menu thread: stop() blocks up to 3s and alive() up to
            // 300ms - holding the daemon mutex here would freeze the tray
            let app2 = app.clone();
            std::thread::spawn(move || {
                let state = app2.state::<AppState>();
                let mut daemon = state.daemon.lock().unwrap();
                if daemon.owns_running() {
                    daemon.stop();
                } else {
                    let external = laris::read_peer(&peers_path())
                        .map(|p| laris::alive(&p.url))
                        .unwrap_or(false);
                    if external {
                        // the tray never kills a daemon it didn't start
                        notify(&app2, "Ditado foi iniciado fora do VOXIS - encerre-o por lá");
                    } else if let Err(e) = daemon.spawn() {
                        notify(&app2, &format!("Falha ao iniciar ditado: {e}"));
                    }
                }
            });
        }
        "hands_free" => {
            let app2 = app.clone();
            std::thread::spawn(move || {
                let path = settings::laris_settings_path();
                let mut map = settings::read_json_map(&path);
                let now_on =
                    map.get("ASSISTANT_MODE").and_then(|v| v.as_str()) == Some("always_on");
                let next = if now_on { "ptt" } else { "always_on" };
                map.insert("ASSISTANT_MODE".into(), serde_json::Value::String(next.into()));
                if let Err(e) = settings::write_json_atomic(&path, &serde_json::Value::Object(map)) {
                    notify(&app2, &format!("Falha ao salvar: {e}"));
                    return;
                }
                // settings load at daemon start only - restart our own daemon to apply
                let state = app2.state::<AppState>();
                let mut daemon = state.daemon.lock().unwrap();
                if daemon.owns_running() {
                    daemon.stop();
                    if let Err(e) = daemon.spawn() {
                        notify(&app2, &format!("Falha ao reiniciar ditado: {e}"));
                    }
                }
            });
        }
        id if id.starts_with("theme:") => {
            let parts: Vec<&str> = id.splitn(3, ':').collect();
            if let [_, key, value] = parts[..] {
                if let Some(peer) = laris::read_peer(&peers_path()) {
                    if let Err(e) = laris::set_theme(&peer, serde_json::json!({ key: value })) {
                        notify(app, &format!("Falha ao aplicar tema: {e}"));
                    }
                }
            }
        }
        _ => {}
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // must be the first registered plugin; a second launch lands here in
        // the FIRST instance and we just surface the settings window
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            commands::show_settings_window(app);
        }))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            commands::get_settings,
            commands::save_laris_settings,
            commands::save_miris_config,
            commands::save_theme,
        ])
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            let mut config = settings::load_tray_config();
            // packaged builds ship miris frozen as a resource; tray.json's
            // default path only exists on a machine with the pip install
            let resource_dir = app.path().resource_dir().ok();
            let miris_bin =
                settings::effective_miris_bin(&config.miris_bin, resource_dir.as_deref());
            config.miris_bin = miris_bin;
            let daemon = {
                #[cfg(windows)]
                {
                    let engine = resource_dir
                        .as_ref()
                        .map(|r| r.join("engine").join("laris-engine.exe"))
                        // is_file, not exists: engine/ ships a .gitkeep
                        // placeholder, so the dir can be there with no engine
                        .filter(|p| p.is_file());
                    match engine {
                        Some(bin) => laris::LarisDaemon::with_engine(
                            bin,
                            settings::config_dir().join("laris-engine.log"),
                        ),
                        None => laris::LarisDaemon::new(PathBuf::from(&config.laris_dir)),
                    }
                }
                #[cfg(not(windows))]
                {
                    laris::LarisDaemon::new(PathBuf::from(&config.laris_dir))
                }
            };
            app.manage(AppState {
                config,
                daemon: Mutex::new(daemon),
                processing: AtomicBool::new(false),
                menu_dirty: AtomicBool::new(false),
                last_orb_rect: Mutex::new(None),
                orb_ready: AtomicBool::new(false),
                boot_status: Mutex::new(BootStatus::default()),
            });

            let snap = take_snapshot(app.handle(), &app.state::<AppState>());
            let menu = build_menu(app.handle(), &snap)?;
            let icon = tauri::image::Image::from_bytes(include_bytes!("../icons/tray-idle.png"))?;
            let builder = TrayIconBuilder::with_id("voxis")
                .icon(icon)
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| handle_menu(app, event.id().as_ref()));

            // Template icons are an AppKit concept - the system retints them for
            // the menu bar. No-op on Windows, so keep it macOS-only. Shadowing
            // instead of `let mut` avoids an unused-mut warning elsewhere.
            #[cfg(target_os = "macos")]
            let builder = builder.icon_as_template(true);

            let tray = builder.build(app)?;
            set_tray_icon(&tray, snap.recording.is_some());

            // poll loop: snapshot off the main thread, menu mutations on it
            // (macOS requires menu construction on the main thread)
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let mut last = snap;
                loop {
                    // Sleep in slices instead of one 2s block: when the
                    // long-poll thread flags the menu dirty - which is how
                    // "carregando modelo..." turns into a usable menu - the
                    // repaint lands in ~250ms rather than waiting out the rest
                    // of the tick. The tick itself stays at 2s; only the
                    // reaction to an explicit flag is faster.
                    {
                        let state = handle.state::<AppState>();
                        for _ in 0..8 {
                            std::thread::sleep(Duration::from_millis(250));
                            if state.menu_dirty.load(Ordering::SeqCst) {
                                break;
                            }
                        }
                    }
                    let state = handle.state::<AppState>();
                    let dirty = state.menu_dirty.swap(false, Ordering::SeqCst);
                    let current = take_snapshot(&handle, &state);
                    if current == last && !dirty {
                        continue;
                    }
                    let recording_changed =
                        current.recording.is_some() != last.recording.is_some();
                    // Store the rect for the long-poll thread to use without redundant GET /theme
                    if let Ok(mut last_rect) = state.last_orb_rect.lock() {
                        *last_rect = current.rect;
                    }
                    last = current.clone();
                    let handle2 = handle.clone();
                    let _ = handle.run_on_main_thread(move || {
                        if let Some(tray) = handle2.tray_by_id("voxis") {
                            if let Ok(menu) = build_menu(&handle2, &current) {
                                let _ = tray.set_menu(Some(menu));
                            }
                            // The menu only exists while the user holds it
                            // open, and an open native menu does not repaint -
                            // the tooltip is where a changing value is
                            // actually seen.
                            let _ = tray.set_tooltip(Some(tray_tooltip(&current)));
                            if recording_changed {
                                set_tray_icon(&tray, current.recording.is_some());
                            }
                        }
                        // The 2s poll owns size/position and the URL; visibility is
                        // owned by the long-poll thread. sync() is idempotent and
                        // guards its own change detection, so calling it every tick
                        // is cheap and is what lets a restarted daemon's new token
                        // reach the window (the rect alone may not have changed).
                        if current.laris_alive {
                            if let Some(peer) = laris::read_peer(&peers_path()) {
                                let url = overlay::overlay_url(&peer);
                                let _ = overlay::sync(&handle2, &url, current.rect, false);
                            }
                        } else {
                            // Engine died: tear the window down instead of leaving it
                            // reconnecting to nothing with a token that is now void.
                            overlay::close(&handle2);
                        }
                    });
                }
            });

            // Long-poll thread: monitor overlay state (visibility, readiness) and
            // update the orb window when it changes. This is separate from the
            // 2s theme poll and runs continuously in the background.
            let handle_lp = app.handle().clone();
            std::thread::spawn(move || {
                let mut last_visible = false;
                let mut serial = 0i64;
                let mut backoff = Duration::from_secs(1);
                const MAX_BACKOFF: Duration = Duration::from_secs(5);
                loop {
                    std::thread::sleep(backoff);
                    let peer = match laris::read_peer(&peers_path()) {
                        Some(p) => p,
                        None => {
                            backoff = Duration::from_secs(1);
                            continue;
                        }
                    };
                    match laris::get_overlay_state(&peer, serial, 20.0) {
                        Ok(state) => {
                            // The request itself long-polls for up to 20s, so
                            // sleeping a whole second between calls only delays
                            // noticing the next change. Keep it short on the
                            // success path; the error path still backs off.
                            backoff = Duration::from_millis(100);
                            // Publish readiness for the menu label. Flag the menu
                            // dirty on change so the next 2s tick rebuilds it even
                            // though nothing else in the snapshot moved.
                            {
                                let app_state = handle_lp.state::<AppState>();
                                let was = app_state.orb_ready.swap(state.ready, Ordering::SeqCst);
                                let mut dirty = was != state.ready;
                                // The engine only bumps its serial when this
                                // actually changes, so this compare is what
                                // keeps a download from repainting the menu
                                // more often than it advances.
                                let incoming = BootStatus {
                                    text: state.status.clone(),
                                    progress: state.progress,
                                };
                                if let Ok(mut current) = app_state.boot_status.lock() {
                                    if *current != incoming {
                                        *current = incoming;
                                        dirty = true;
                                    }
                                }
                                if dirty {
                                    app_state.menu_dirty.store(true, Ordering::SeqCst);
                                }
                            }
                            if state.serial != serial {
                                serial = state.serial;
                                if state.visible != last_visible {
                                    last_visible = state.visible;
                                    let handle_sync = handle_lp.clone();
                                    let _ = handle_lp.run_on_main_thread(move || {
                                        if let Some(peer) = laris::read_peer(&peers_path()) {
                                            let url = overlay::overlay_url(&peer);
                                            // Get the last known rect from the 2s poll thread
                                            let app_state = handle_sync.state::<AppState>();
                                            let rect = app_state.last_orb_rect.lock().ok().and_then(|r| *r);
                                            let _ = overlay::sync(&handle_sync, &url, rect, last_visible);
                                        }
                                    });
                                }
                            }
                        }
                        Err(_) => {
                            // Connection error, malformed body, or 403: assume not visible
                            if last_visible {
                                last_visible = false;
                                let handle_sync = handle_lp.clone();
                                let _ = handle_lp.run_on_main_thread(move || {
                                    let _ = overlay::sync(&handle_sync, "", None, false);
                                });
                            }
                            backoff = (backoff * 2).min(MAX_BACKOFF);
                        }
                    }
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn progress_bar_fills_proportionally() {
        assert_eq!(progress_bar(0.0), "░░░░░░░░░░ 0%");
        assert_eq!(progress_bar(1.0), "██████████ 100%");
        assert_eq!(progress_bar(0.5), "█████░░░░░ 50%");
        // 10 cells, so 43% rounds to 4 filled - the label keeps the real value
        assert_eq!(progress_bar(0.43), "████░░░░░░ 43%");
    }

    #[test]
    fn progress_bar_clamps_instead_of_panicking() {
        // repeat() on a negative-turned-huge count would panic, and a bad
        // number from the engine must not take the tray down
        assert_eq!(progress_bar(-1.0), "░░░░░░░░░░ 0%");
        assert_eq!(progress_bar(2.5), "██████████ 100%");
    }

    fn loading(text: &str, progress: Option<f64>) -> Snapshot {
        Snapshot {
            laris_alive: true,
            ready: false,
            boot_status: BootStatus { text: Some(text.to_string()), progress },
            ..Default::default()
        }
    }

    #[test]
    fn tooltip_shows_the_bar_while_loading() {
        let tip = tray_tooltip(&loading("baixando modelo 43% de 547 MB", Some(0.43)));
        assert!(tip.contains("baixando modelo"), "{tip}");
        assert!(tip.contains("████"), "{tip}");
    }

    #[test]
    fn tooltip_without_a_fraction_omits_the_bar() {
        let tip = tray_tooltip(&loading("carregando modelo", None));
        assert!(tip.contains("carregando modelo"), "{tip}");
        assert!(!tip.contains('█'), "{tip}");
    }

    #[test]
    fn tooltip_is_plain_once_ready() {
        let snap = Snapshot { laris_alive: true, ready: true, ..Default::default() };
        assert_eq!(tray_tooltip(&snap), "VOXIS");
    }
}
