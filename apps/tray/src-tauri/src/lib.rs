mod commands;
mod laris;
mod miris;
// The orb is a tray window only on Windows; elsewhere the daemon draws its own
// and these are no-op stubs.
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
    /// Last orb rect from the 2s poll, read by the Windows long-poll thread
    /// so showing the orb needs no extra GET /theme.
    pub last_orb_rect: Mutex<Option<overlay::OrbRect>>,
    /// Boot progress the Windows long-poll thread reads off /overlay/state,
    /// shown in the dictation label and the tooltip while the model loads. A
    /// 547 MB first-run download with no sign of life reads as a hung app.
    pub boot_status: Mutex<BootStatus>,
}

#[derive(Debug, Clone, PartialEq, Default)]
struct Snapshot {
    /// Active session: (id, minutes, state). None when nothing is running.
    meeting: Option<(String, i64, miris::SessionState)>,
    /// Newest pending session: (id, displayed state, error message).
    pending: Option<(String, miris::SessionState, Option<String>)>,
    laris_alive: bool,
    ptt_trusted: bool, // false = daemon up but macOS denies keyboard monitoring
    laris_ready: bool, // false = daemon up, model still loading
    hands_free: bool,
    dictating: bool, // the daemon's toggle left the mic listening (Linux)
    has_last_note: bool,
    theme: Option<(String, String, String)>, // (archetype, palette, position)
    rect: Option<overlay::OrbRect>, // Windows: where the orb window goes, logical px
    boot_status: BootStatus,        // what the engine is doing while !laris_ready
}

/// One primary action represents only the active session; a second item
/// represents the newest pending one. Disabled rows explain why.
fn primary_action(active: Option<miris::SessionState>) -> (&'static str, &'static str, bool) {
    match active {
        None => ("miris_start", "Gravar reunião", true),
        Some(miris::SessionState::Starting) => ("noop", "Iniciando gravação...", false),
        Some(miris::SessionState::Recording) => ("miris_stop", "Parar gravação", true),
        Some(miris::SessionState::Stopping) => ("noop", "Parando gravação...", false),
        Some(miris::SessionState::Processing) => ("noop", "Processando reunião...", false),
        // captured/interrupted/completed/failed are not active work
        Some(_) => ("miris_start", "Gravar reunião", true),
    }
}

fn pending_action(state: miris::SessionState) -> Option<(&'static str, &'static str)> {
    match state {
        miris::SessionState::Captured => Some(("miris_process", "Processar gravação")),
        miris::SessionState::Interrupted => Some(("miris_recover", "Recuperar gravação")),
        _ => None,
    }
}

/// A detached recording must never be orphaned by a quit: Sair is only
/// offered when the latest session reached a stable state (captured,
/// completed, interrupted, failed - or none at all).
fn quit_enabled(active: Option<miris::SessionState>) -> bool {
    !active.is_some_and(miris::SessionState::is_active)
}

/// Session ids are %Y%m%d-%H%M%S. Menu ids embed them; never let anything
/// that is not exactly that reach the CLI as a path component.
fn safe_session_id(raw: &str) -> Option<String> {
    let id = raw.trim();
    (!id.is_empty() && id.chars().all(|c| c.is_ascii_digit() || c == '-'))
        .then(|| id.to_owned())
}

// Warn once when the daemon comes up without keyboard permission: the edge
// INTO the bad state, so the tray nags on transition, not every poll tick.
fn should_warn_untrusted(last: &Snapshot, current: &Snapshot) -> bool {
    current.laris_alive && !current.ptt_trusted && (!last.laris_alive || last.ptt_trusted)
}

/// Only an active recording session paints the red icon - a pending
/// interruption or a captured session does not.
fn is_recording(snap: &Snapshot) -> bool {
    meeting_state(snap) == Some(miris::SessionState::Recording)
}

/// The red icon means the mic is open: a meeting recording, or dictation
/// listening after a toggle (Linux, where there is no orb to show it).
fn shows_live_icon(snap: &Snapshot) -> bool {
    is_recording(snap) || snap.dictating
}

fn meeting_state(snap: &Snapshot) -> Option<miris::SessionState> {
    snap.meeting.as_ref().map(|(_, _, s)| *s)
}

/// Liveness is not readiness: uvicorn answers on :8421 seconds before the
/// model is loaded and the key listener attached.
fn dictation_status_label(alive: bool, ready: bool) -> &'static str {
    match (alive, ready) {
        (false, _) => "Ditado indisponível",
        (true, false) => "Carregando modelo...",
        (true, true) => "Ditado ativo",
    }
}

/// The status row, with the engine's own account of a slow boot when it gives
/// one (Windows: downloading the model, compiling GPU shaders).
fn dictation_label(snap: &Snapshot) -> String {
    if snap.laris_alive && !snap.laris_ready {
        match (snap.boot_status.text.as_deref(), snap.boot_status.progress) {
            (Some(text), Some(p)) if !text.is_empty() => {
                return format!("Carregando: {text} {}", progress_bar(p));
            }
            (Some(text), None) if !text.is_empty() => return format!("Carregando: {text}"),
            _ => {}
        }
    }
    dictation_status_label(snap.laris_alive, snap.laris_ready).to_owned()
}

/// `0.43` -> `████░░░░░░ 43%`. A native menu item is text, so the bar is
/// block characters.
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

/// Hover text for the tray icon: an open native menu does not repaint, so this
/// is where a changing boot progress is actually seen.
fn tray_tooltip(snap: &Snapshot) -> String {
    if snap.laris_alive && !snap.laris_ready {
        return match (snap.boot_status.text.as_deref(), snap.boot_status.progress) {
            (Some(text), Some(p)) => format!("VOXIS - {text}\n{}", progress_bar(p)),
            (Some(text), None) => format!("VOXIS - {text}"),
            _ => "VOXIS - carregando modelo...".to_owned(),
        };
    }
    if is_recording(snap) {
        return "VOXIS - reunião em andamento".to_owned();
    }
    "VOXIS".to_owned()
}

fn hands_free_enabled(alive: bool, ready: bool) -> bool {
    alive && ready
}

fn peers_path() -> PathBuf {
    settings::config_dir().join("peers.json")
}

/// True when a daemon we did not spawn is already answering on the peer url
/// (e.g. `python -m laris` started by hand per docs/INSTALL.md). Spawning a
/// second daemon on top of it fights over peers.json and the keyboard
/// listener - the tray must defer instead.
fn external_daemon_alive() -> bool {
    laris::read_peer(&peers_path()).map(|p| laris::alive(&p.url)).unwrap_or(false)
}

/// Un-owned and unreachable is the only state worth recovering: an external
/// daemon (alive=true) is not ours to manage, and an owned daemon is either
/// alive or on its way up. Capped so a daemon that fails on every start
/// (bad laris_dir, model download failing repeatedly) doesn't spin forever.
fn should_respawn(owns: bool, alive: bool, attempts: u32, cap: u32) -> bool {
    !owns && !alive && attempts < cap
}

fn sessions_dir(state: &AppState) -> PathBuf {
    PathBuf::from(&state.config.miris_home).join("sessions")
}

/// The primary monitor's work area in logical pixels - what the daemon places
/// the orb against - and its origin. Work area, not size: a "bottom-*" orb
/// lands above the taskbar instead of behind it.
#[cfg(windows)]
fn orb_screen(app: &AppHandle) -> Option<((f64, f64), (f64, f64))> {
    let monitor = app.primary_monitor().ok().flatten()?;
    let scale = monitor.scale_factor();
    let area = monitor.work_area();
    let size = area.size.to_logical::<f64>(scale);
    let pos = area.position.to_logical::<f64>(scale);
    Some(((size.width, size.height), (pos.x, pos.y)))
}

#[cfg(not(windows))]
fn orb_screen(_app: &AppHandle) -> Option<((f64, f64), (f64, f64))> {
    None // the daemon draws and places its own orb
}

fn take_snapshot(app: &AppHandle, state: &AppState) -> Snapshot {
    let sessions = sessions_dir(state);
    let snap = miris::snapshot(&sessions);
    let meeting = snap.active.as_ref().map(|v| {
        let mins = miris::recording_minutes(&v.manifest.session_id, chrono::Local::now())
            .unwrap_or(0);
        (v.manifest.session_id.clone(), mins, v.manifest.state)
    });
    let pending = snap.pending.as_ref().map(|v| {
        (
            v.manifest.session_id.clone(),
            v.derived_state,
            v.manifest.error.as_ref().map(|e| e.message.clone()),
        )
    });
    let peer = laris::read_peer(&peers_path());
    let laris_alive = peer.as_ref().map(|p| laris::alive(&p.url)).unwrap_or(false);
    // ponytail: theme fetched every tick while laris is up - localhost HTTP,
    // negligible; cache only if it ever shows up in a profile
    let screen = orb_screen(app);
    let theme_body = peer
        .filter(|_| laris_alive)
        .and_then(|p| laris::get_theme(&p, screen.map(|(size, _)| size)).ok());
    // the daemon answers in work-area coordinates; the window wants the
    // desktop's, which differ when the primary monitor is not at the origin
    let rect = theme_body.as_ref().and_then(|b| b.get("rect")).and_then(|r| {
        let (ox, oy) = screen.map(|(_, origin)| origin).unwrap_or_default();
        Some(overlay::OrbRect {
            x: ox + r.get("x")?.as_f64()?,
            y: oy + r.get("y")?.as_f64()?,
            w: r.get("w")?.as_f64()?,
            h: r.get("h")?.as_f64()?,
        })
    });
    // absent field = old daemon: default trusted so we never nag on unknowns
    let ptt_trusted = theme_body
        .as_ref()
        .and_then(|b| b.get("ptt_trusted")?.as_bool())
        .unwrap_or(true);
    let laris_ready = theme_body
        .as_ref()
        .and_then(|b| b.get("ready")?.as_bool())
        .unwrap_or(true);
    // absent field = macOS or an old daemon: never claim the mic is open
    let dictating = theme_body
        .as_ref()
        .and_then(|b| b.get("dictating")?.as_bool())
        .unwrap_or(false);
    let theme = theme_body.and_then(|body| {
        let t = body.get("theme")?;
        Some((
            t.get("archetype")?.as_str()?.to_owned(),
            t.get("palette")?.as_str()?.to_owned(),
            t.get("position")?.as_str()?.to_owned(),
        ))
    });
    let laris_settings = settings::read_json_map(&settings::laris_settings_path());
    let hands_free =
        laris_settings.get("ASSISTANT_MODE").and_then(|v| v.as_str()) == Some("always_on");
    Snapshot {
        meeting,
        pending,
        laris_alive,
        ptt_trusted,
        laris_ready,
        hands_free,
        dictating,
        has_last_note: snap.last_note.is_some(),
        theme,
        rect,
        boot_status: state.boot_status.lock().map(|b| b.clone()).unwrap_or_default(),
    }
}

fn build_menu(app: &AppHandle, snap: &Snapshot) -> tauri::Result<Menu<Wry>> {
    let active_state = meeting_state(snap);
    let (id, base_label, enabled) = primary_action(active_state);
    let label = if active_state == Some(miris::SessionState::Recording) {
        let mins = snap.meeting.as_ref().map(|(_, m, _)| *m).unwrap_or(0);
        format!("{base_label} ({mins} min)")
    } else {
        base_label.to_owned()
    };
    let meeting = MenuItem::with_id(app, id, label, enabled, None::<&str>)?;

    let mut items: Vec<Box<dyn IsMenuItem<Wry>>> = vec![Box::new(meeting)];
    if let Some((session_id, state, _)) = &snap.pending {
        if let Some((base, text)) = pending_action(*state) {
            items.push(Box::new(MenuItem::with_id(
                app,
                format!("{base}:{session_id}"),
                text,
                true,
                None::<&str>,
            )?));
        }
    }

    let last_note =
        MenuItem::with_id(app, "last_note", "Última nota", snap.has_last_note, None::<&str>)?;
    items.push(Box::new(last_note));
    let sep1 = PredefinedMenuItem::separator(app)?;
    items.push(Box::new(sep1));
    // status, not a switch: dictation is always on and cmd_r is the control.
    // Own id, not "noop" - the meeting item already uses that one while
    // processing, and two items sharing an id in one menu is asking for a
    // handler to fire on the wrong row.
    let dictation = MenuItem::with_id(
        app,
        "dictation_status",
        dictation_label(snap),
        false, // disabled: nothing to click
        None::<&str>,
    )?;
    items.push(Box::new(dictation));
    // With a key, the checkbox only permits hands-free: the double-tap starts
    // it, and this label is the only place a user learns that. Linux's toggle
    // shortcut is the start itself.
    let hands_free_label = if cfg!(target_os = "linux") {
        "Hands-free"
    } else {
        "Hands-free (duplo-toque na tecla)"
    };
    let hands_free = CheckMenuItem::with_id(
        app, "hands_free", hands_free_label,
        hands_free_enabled(snap.laris_alive, snap.laris_ready),
        snap.hands_free, None::<&str>,
    )?;
    items.push(Box::new(hands_free));

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
    let theme_menu = Submenu::with_id_and_items(
        app, "theme", "Tema do orb",
        hands_free_enabled(snap.laris_alive, snap.laris_ready),
        &refs,
    )?;
    items.push(Box::new(theme_menu));

    let sep2 = PredefinedMenuItem::separator(app)?;
    items.push(Box::new(sep2));
    let settings_item =
        MenuItem::with_id(app, "settings", "Configurações...", true, None::<&str>)?;
    items.push(Box::new(settings_item));
    let quit = MenuItem::with_id(
        app, "quit", "Sair",
        quit_enabled(active_state),
        None::<&str>,
    )?;
    items.push(Box::new(quit));

    let refs: Vec<&dyn IsMenuItem<Wry>> = items.iter().map(|b| b.as_ref()).collect();
    Menu::with_items(app, &refs)
}

fn set_tray_icon(tray: &TrayIcon, recording: bool) {
    let (bytes, template): (&[u8], bool) = if recording {
        (include_bytes!("../icons/tray-rec.png"), false)
    } else {
        (include_bytes!("../icons/tray-idle.png"), true)
    };
    if let Ok(img) = tauri::image::Image::from_bytes(bytes) {
        // icon first, template after: macOS applies the template attribute to
        // the CURRENT image - the reverse order leaves the new image raw-color
        // and it vanishes against a similarly colored wallpaper
        let _ = tray.set_icon(Some(img));
        let _ = tray.set_icon_as_template(template);
    }
}

fn notify(app: &AppHandle, body: &str) {
    let _ = app.notification().builder().title("VOXIS").body(body).show();
}

/// Raise the macOS microphone prompt when it hasn't been decided yet. laris
/// opens the mic from a spawned, bundle-less Python daemon that TCC won't show a
/// dialog for; an in-process objc2 `requestAccess` also stayed a silent no-op.
/// Reading the status via objc2 works, so we do that here and, only when it's
/// notDetermined, spawn the bundled Swift sidecar (grant-mic) which CAN present
/// the prompt. It is signed with the app identity, so the grant lands on
/// VOXIS.app and unblocks the daemon's capture. No-op once decided.
#[cfg(target_os = "macos")]
fn ensure_mic_access() {
    use objc2::msg_send;
    use objc2::runtime::AnyClass;
    use objc2_foundation::NSString;

    #[link(name = "AVFoundation", kind = "framework")]
    extern "C" {
        static AVMediaTypeAudio: *const NSString;
    }
    let audio: &NSString = unsafe { &*AVMediaTypeAudio };
    let Some(av_capture_device) = AnyClass::get(c"AVCaptureDevice") else {
        return;
    };
    // AVAuthorizationStatus: 0 = notDetermined, 3 = authorized
    let status: isize =
        unsafe { msg_send![av_capture_device, authorizationStatusForMediaType: audio] };
    if status != 0 {
        return;
    }
    // Raise the prompt via the bundled GrantMic.app - a short-lived Regular-policy
    // Swift app sharing VOXIS's identity, launched through LaunchServices (the
    // tray's own objc2 requestAccess and bare-subprocess spawns both stayed
    // silent no-ops). It MUST run de-nested: a .app nested inside another bundle
    // is auto-denied mic, a standalone copy gets the dialog - so ditto it out
    // (ditto preserves the signature) and open that. Absent in dev (unbundled).
    let Ok(exe) = std::env::current_exe() else { return };
    let Some(bundled) = exe
        .parent()
        .and_then(|p| p.parent())
        .map(|contents| contents.join("Resources/resources/GrantMic.app"))
    else {
        return;
    };
    if !bundled.exists() {
        return;
    }
    let dest = std::env::temp_dir().join("VOXIS-GrantMic.app");
    if std::process::Command::new("ditto").arg(&bundled).arg(&dest).status().is_ok() {
        let _ = std::process::Command::new("open").arg("-n").arg(&dest).spawn();
    }
}

fn handle_menu(app: &AppHandle, id: &str) {
    let state = app.state::<AppState>();
    state.menu_dirty.store(true, Ordering::SeqCst);
    match id {
        "quit" => {
            // the menu item is disabled during active work, but a click can
            // race a session that started since the last 2s poll - re-check
            if miris::snapshot(&sessions_dir(&state)).active.is_some() {
                return;
            }
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
                    Ok(miris::StopOutcome::Note(note)) => format!(
                        "Nota salva: {}",
                        note.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()
                    ),
                    Ok(miris::StopOutcome::Interrupted) => {
                        "Gravação interrompida: recupere pelo menu".to_owned()
                    }
                    Err(e) => format!("Falha ao processar reunião: {e}"),
                };
                app2.state::<AppState>().processing.store(false, Ordering::SeqCst);
                notify(&app2, &msg);
            });
        }
        id if id.starts_with("miris_recover:") || id.starts_with("miris_process:") => {
            let (base, raw) = id.split_once(':').unwrap_or(("", ""));
            let Some(session_id) = safe_session_id(raw) else { return };
            // same suppression as stop: one CLI action at a time
            if state
                .processing
                .compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
                .is_err()
            {
                return;
            }
            let app2 = app.clone();
            let bin = state.config.miris_bin.clone();
            let recovering = base == "miris_recover";
            std::thread::spawn(move || {
                let result = if recovering {
                    miris::recover(&bin, &session_id).map(|_| None)
                } else {
                    miris::process(&bin, &session_id).map(Some)
                };
                let msg = if recovering {
                    match result {
                        Ok(_) => return, // the poll flips the row to Processar
                        Err(e) => format!("Falha ao recuperar gravação: {e}"),
                    }
                } else {
                    match result {
                        Ok(Some(note)) => format!(
                            "Nota salva: {}",
                            note.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default()
                        ),
                        Ok(None) => unreachable!("process maps to Some"),
                        Err(e) => format!("Falha ao processar reunião: {e}"),
                    }
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
                apply_mode(&app2, next);
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

/// Pushes ASSISTANT_MODE to the live daemon, falling back to a restart only
/// when it cannot be reached over HTTP (an engine from before /mode, or a
/// wedged one). Restarting a reachable daemon for this destroyed the orb and
/// reloaded the model, which is indistinguishable from a crash.
pub fn apply_mode(app: &AppHandle, mode: &str) {
    if let Some(peer) = laris::read_peer(&peers_path()) {
        if laris::set_mode(&peer, mode).is_ok() {
            return;
        }
    }
    let state = app.state::<AppState>();
    let mut daemon = state.daemon.lock().unwrap();
    if daemon.owns_running() {
        daemon.stop();
        if let Err(e) = daemon.spawn() {
            notify(app, &format!("Falha ao reiniciar ditado: {e}"));
        }
    }
    // not running and not ours: the file just written is what its next boot reads
}

/// Windows: follow /overlay/state - show or hide the orb window the moment
/// the daemon does, and publish boot progress for the menu and tooltip. The
/// request itself waits up to 20s for a change, so this is one open call, not
/// a busy loop.
#[cfg(windows)]
fn spawn_orb_state_follower(app: AppHandle) {
    std::thread::spawn(move || {
        let mut last_visible = false;
        let mut serial = 0i64;
        let mut backoff = Duration::from_secs(1);
        loop {
            std::thread::sleep(backoff);
            let Some(peer) = laris::read_peer(&peers_path()) else {
                backoff = Duration::from_secs(1);
                continue;
            };
            match laris::get_overlay_state(&peer, serial, 20.0) {
                Ok(orb) => {
                    backoff = Duration::from_millis(100);
                    let state = app.state::<AppState>();
                    let incoming = BootStatus { text: orb.status.clone(), progress: orb.progress };
                    if let Ok(mut current) = state.boot_status.lock() {
                        if *current != incoming {
                            *current = incoming;
                            // the 2s tick rebuilds the menu; dirty makes it
                            // repaint even though nothing else moved
                            state.menu_dirty.store(true, Ordering::SeqCst);
                        }
                    }
                    serial = orb.serial;
                    if orb.visible != last_visible {
                        last_visible = orb.visible;
                        let app2 = app.clone();
                        let _ = app.run_on_main_thread(move || {
                            if let Some(peer) = laris::read_peer(&peers_path()) {
                                let state = app2.state::<AppState>();
                                let rect = state.last_orb_rect.lock().ok().and_then(|r| *r);
                                let url = overlay::overlay_url(&peer);
                                let _ = overlay::sync(&app2, &url, rect, last_visible);
                            }
                        });
                    }
                }
                Err(_) => {
                    // daemon down, restarting or refusing a stale token: hide
                    if last_visible {
                        last_visible = false;
                        let app2 = app.clone();
                        let _ = app.run_on_main_thread(move || {
                            let _ = overlay::sync(&app2, "", None, false);
                        });
                    }
                    backoff = (backoff * 2).min(Duration::from_secs(5));
                }
            }
        }
    });
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
            #[cfg(target_os = "macos")]
            ensure_mic_access();

            let mut config = settings::load_tray_config();
            let resource_dir = app.path().resource_dir().ok();
            // the installer ships miris frozen as a resource; tray.json's
            // default only exists where the pip install does
            config.miris_bin =
                settings::effective_miris_bin(&config.miris_bin, resource_dir.as_deref());
            // Windows installer: the frozen engine beside the tray. is_file,
            // not exists: engine/ ships a .gitkeep placeholder.
            #[cfg(windows)]
            let engine = resource_dir
                .as_ref()
                .map(|r| r.join("engine").join("laris-engine.exe"))
                .filter(|p| p.is_file());
            #[cfg(not(windows))]
            let engine: Option<PathBuf> = None;
            let logs = settings::config_dir();
            let daemon = match engine {
                // its own name: the frozen engine's log is what a Windows user sends in
                Some(bin) => laris::LarisDaemon::with_engine(bin, logs.join("laris-engine.log")),
                None => laris::LarisDaemon::new(
                    PathBuf::from(&config.laris_dir),
                    Some(logs.join("laris.log")),
                ),
            };
            app.manage(AppState {
                config,
                daemon: Mutex::new(daemon),
                processing: AtomicBool::new(false),
                menu_dirty: AtomicBool::new(false),
                last_orb_rect: Mutex::new(None),
                boot_status: Mutex::new(BootStatus::default()),
            });

            // The model costs ~3.6s and 276MB to load. Loading it once per
            // session beats reloading it per toggle; "Sair" is what releases it.
            {
                let state = app.state::<AppState>();
                let mut daemon = state.daemon.lock().unwrap();
                if external_daemon_alive() {
                    // don't spawn on top of it: second process overwrites
                    // peers.json with a token the first server rejects, and
                    // still starts its own keyboard listener alongside it
                    notify(app.handle(), "Ditado foi iniciado fora do VOXIS - encerre-o por lá");
                } else if let Err(e) = daemon.spawn() {
                    // a bad laris_dir would otherwise fail silently at boot -
                    // the old code path surfaced this from the menu handler
                    notify(app.handle(), &format!("Falha ao iniciar ditado: {e}"));
                }
            }

            let snap = take_snapshot(app.handle(), &app.state::<AppState>());
            let menu = build_menu(app.handle(), &snap)?;
            let icon = tauri::image::Image::from_bytes(include_bytes!("../icons/tray-idle.png"))?;
            let tray = TrayIconBuilder::with_id("voxis")
                .icon(icon)
                .icon_as_template(true)
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| handle_menu(app, event.id().as_ref()))
                .build(app)?;
            set_tray_icon(&tray, shows_live_icon(&snap));

            // poll loop: snapshot off the main thread, menu mutations on it
            // (macOS requires menu construction on the main thread)
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let mut last = snap;
                // process-lifetime cap, not per-tick: a daemon that fails on
                // every start (bad install, model download broken) must stop
                // retrying, not burn CPU/notifications until the app quits
                let mut respawn_attempts: u32 = 0;
                const RESPAWN_CAP: u32 = 3;
                loop {
                    // 2s in slices: a flag raised mid-tick (a click, the boot
                    // finishing) repaints in ~250ms instead of up to 2s later
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
                    if let Ok(mut rect) = state.last_orb_rect.lock() {
                        *rect = current.rect;
                    }

                    // recover from a dead tray-owned daemon (crash, OOM, a
                    // model download that failed on first boot) - every other
                    // restart path is gated on owns_running() and stays a
                    // permanent no-op once the child has exited
                    let owns = state.daemon.lock().unwrap().owns_running();
                    if should_respawn(owns, current.laris_alive, respawn_attempts, RESPAWN_CAP) {
                        respawn_attempts += 1;
                        if let Err(e) = state.daemon.lock().unwrap().spawn() {
                            notify(&handle, &format!("Falha ao reiniciar ditado: {e}"));
                        }
                    }

                    if current == last && !dirty {
                        continue;
                    }
                    let recording_changed = shows_live_icon(&current) != shows_live_icon(&last);
                    // an active capture that turned into a pending interrupted
                    // session is the user's four-second notification target
                    if last.meeting.is_some() && !current.meeting.is_some() {
                        if let Some((session, state, error)) = &current.pending {
                            if *state == miris::SessionState::Interrupted {
                                let reason = error.clone().unwrap_or_else(|| {
                                    "falha de captura".to_owned()
                                });
                                notify(&handle, &format!("Gravação interrompida: {reason}"));
                                let _ = session; // the pending row offers the recovery
                            }
                        }
                    }
                    if should_warn_untrusted(&last, &current) {
                        notify(&handle, "Ditado sem permissão: ative VOXIS em Ajustes › \
                            Privacidade e Segurança › Acessibilidade E Monitoramento de \
                            Entrada, depois reinicie o VOXIS.");
                    }
                    last = current.clone();
                    let handle2 = handle.clone();
                    let _ = handle.run_on_main_thread(move || {
                        if let Some(tray) = handle2.tray_by_id("voxis") {
                            if let Ok(menu) = build_menu(&handle2, &current) {
                                let _ = tray.set_menu(Some(menu));
                            }
                            let _ = tray.set_tooltip(Some(tray_tooltip(&current)));
                            if recording_changed {
                                set_tray_icon(&tray, shows_live_icon(&current));
                            }
                        }
                        // Windows orb window: this tick owns its URL, size and
                        // position (visibility belongs to the state follower).
                        // sync() is idempotent, and calling it every tick is
                        // what hands a restarted daemon's new token to the
                        // window; a dead daemon's window is torn down.
                        #[cfg(windows)]
                        match laris::read_peer(&peers_path()).filter(|_| current.laris_alive) {
                            Some(peer) => {
                                let url = overlay::overlay_url(&peer);
                                let _ = overlay::sync(&handle2, &url, current.rect, false);
                            }
                            None => overlay::close(&handle2),
                        }
                    });
                }
            });
            #[cfg(windows)]
            spawn_orb_state_follower(app.handle().clone());
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app, event| {
            if let tauri::RunEvent::ExitRequested { code, api, .. } = event {
                if should_prevent_exit(code) {
                    api.prevent_exit();
                }
            }
        });
}

/// The tray owns no permanent window, so closing Settings leaves the runtime
/// with none and it asks to exit - taking dictation down with it. Exit code
/// None is that request; Some means "Sair" called app.exit and must proceed.
fn should_prevent_exit(code: Option<i32>) -> bool {
    code.is_none()
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
        // a bad number from the engine must not take the tray down
        assert_eq!(progress_bar(-1.0), "░░░░░░░░░░ 0%");
        assert_eq!(progress_bar(2.5), "██████████ 100%");
    }

    fn loading(text: &str, progress: Option<f64>) -> Snapshot {
        Snapshot {
            laris_alive: true,
            laris_ready: false,
            boot_status: BootStatus { text: Some(text.to_owned()), progress },
            ..Default::default()
        }
    }

    #[test]
    fn a_loading_engine_says_what_it_is_doing() {
        let snap = loading("baixando modelo 43% de 547 MB", Some(0.43));
        assert!(dictation_label(&snap).contains("baixando modelo"));
        let tip = tray_tooltip(&snap);
        assert!(tip.contains("baixando modelo") && tip.contains("████"), "{tip}");
        let quiet = tray_tooltip(&loading("carregando modelo", None));
        assert!(!quiet.contains('█'), "{quiet}");
    }

    #[test]
    fn an_engine_that_reports_nothing_keeps_the_generic_labels() {
        let snap = Snapshot { laris_alive: true, laris_ready: false, ..Default::default() };
        assert_eq!(dictation_label(&snap), "Carregando modelo...");
        assert_eq!(tray_tooltip(&snap), "VOXIS - carregando modelo...");
        let ready = Snapshot { laris_alive: true, laris_ready: true, ..Default::default() };
        assert_eq!(dictation_label(&ready), "Ditado ativo");
        assert_eq!(tray_tooltip(&ready), "VOXIS");
    }

    #[test]
    fn closing_the_settings_window_must_not_exit_the_tray() {
        // VOXIS is an Accessory app with no permanent window: when Settings
        // closes, the runtime asks to exit because no window is left. code
        // None = that runtime request; Some = the user picked "Sair"
        // (app.exit), which must still go through.
        assert!(should_prevent_exit(None), "closing a window must not kill the tray");
        assert!(!should_prevent_exit(Some(0)), "the Sair menu item must still exit");
    }


    fn snap(laris_alive: bool, ptt_trusted: bool) -> Snapshot {
        Snapshot { laris_alive, ptt_trusted, ..Default::default() }
    }

    #[test]
    fn warns_on_transition_into_untrusted() {
        // daemon just came up (menu -> Ditado) without keyboard permission
        assert!(should_warn_untrusted(&snap(false, true), &snap(true, false)));
        // was trusted, permission lost/re-probed as denied
        assert!(should_warn_untrusted(&snap(true, true), &snap(true, false)));
    }

    #[test]
    fn silent_when_already_untrusted_or_fine() {
        // steady bad state must not nag every 2s tick
        assert!(!should_warn_untrusted(&snap(true, false), &snap(true, false)));
        // trusted daemon
        assert!(!should_warn_untrusted(&snap(false, true), &snap(true, true)));
        // daemon down
        assert!(!should_warn_untrusted(&snap(true, false), &snap(false, true)));
    }

    #[test]
    fn dictation_label_distinguishes_loading_from_ready() {
        // The whole point of this work: "Ditado" must not appear while the model
        // is still loading, because cmd_r does nothing during that window.
        assert_eq!(dictation_status_label(true, true), "Ditado ativo");
        assert_eq!(dictation_status_label(true, false), "Carregando modelo...");
        assert_eq!(dictation_status_label(false, false), "Ditado indisponível");
        // a dead daemon is never ready, whatever a stale payload claims
        assert_eq!(dictation_status_label(false, true), "Ditado indisponível");
    }

    #[test]
    fn the_icon_turns_red_while_dictation_is_listening() {
        // Linux has no orb: with no meeting running, the tray icon is the
        // only sign that a toggle left the mic open
        let listening = Snapshot { dictating: true, ..Default::default() };
        assert!(shows_live_icon(&listening));
    }

    #[test]
    fn the_icon_stays_idle_with_no_meeting_and_no_dictation() {
        assert!(!shows_live_icon(&Snapshot::default()));
    }

    #[test]
    fn hands_free_is_only_offered_once_the_model_is_loaded() {
        // toggling hands-free against a daemon that has not finished warming
        // silently does nothing, which is the failure mode being removed
        assert!(!hands_free_enabled(true, false));
        assert!(hands_free_enabled(true, true));
        assert!(!hands_free_enabled(false, true));
    }

    #[test]
    fn respawns_a_dead_unowned_daemon_below_the_cap() {
        // this is the recovery path itself: our child exited (crash, OOM,
        // failed model download) and nothing else will bring it back
        assert!(should_respawn(false, false, 0, 3));
        assert!(should_respawn(false, false, 2, 3));
    }

    #[test]
    fn stops_respawning_once_the_cap_is_reached() {
        // a daemon that fails on every start must not spin forever
        assert!(!should_respawn(false, false, 3, 3));
        assert!(!should_respawn(false, false, 10, 3));
    }

    #[test]
    fn never_respawns_over_a_reachable_external_daemon() {
        // alive but not owned by us = someone else's process (docs/INSTALL.md
        // standalone run) - not ours to manage, whatever the attempt count
        assert!(!should_respawn(false, true, 0, 3));
    }

    #[test]
    fn never_respawns_a_live_owned_daemon() {
        assert!(!should_respawn(true, true, 0, 3));
        // owned but not yet answering the TCP probe - still starting, not dead
        assert!(!should_respawn(true, false, 0, 3));
    }

    #[test]
    fn menu_labels_follow_lifecycle() {
        assert_eq!(primary_action(None), ("miris_start", "Gravar reunião", true));
        assert_eq!(
            primary_action(Some(miris::SessionState::Starting)).1,
            "Iniciando gravação..."
        );
        assert_eq!(
            primary_action(Some(miris::SessionState::Recording)).0,
            "miris_stop"
        );
        assert_eq!(
            primary_action(Some(miris::SessionState::Stopping)).1,
            "Parando gravação..."
        );
        assert_eq!(
            primary_action(Some(miris::SessionState::Processing)).1,
            "Processando reunião..."
        );
        assert_eq!(
            pending_action(miris::SessionState::Interrupted).map(|(id, _)| id),
            Some("miris_recover")
        );
        assert_eq!(
            pending_action(miris::SessionState::Captured).map(|(id, _)| id),
            Some("miris_process")
        );
        assert!(pending_action(miris::SessionState::Completed).is_none());
    }

    #[test]
    fn quit_is_disabled_only_during_active_work() {
        assert!(!quit_enabled(Some(miris::SessionState::Recording)));
        assert!(!quit_enabled(Some(miris::SessionState::Processing)));
        assert!(!quit_enabled(Some(miris::SessionState::Starting)));
        assert!(!quit_enabled(Some(miris::SessionState::Stopping)));
        assert!(quit_enabled(None));
        assert!(quit_enabled(Some(miris::SessionState::Interrupted)));
        assert!(quit_enabled(Some(miris::SessionState::Captured)));
    }

    #[test]
    fn safe_session_id_only_accepts_timestamp_names() {
        assert_eq!(
            safe_session_id("20260914-143000").as_deref(),
            Some("20260914-143000")
        );
        assert_eq!(safe_session_id("../etc"), None);
        assert_eq!(safe_session_id("x; rm -rf /"), None);
        assert_eq!(safe_session_id(""), None);
    }
}
