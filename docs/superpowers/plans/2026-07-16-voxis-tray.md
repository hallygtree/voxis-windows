# VOXIS Tray Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cross-platform system-tray app (Tauri v2) that controls MIRIS recording, the LARIS dictation daemon and the orb theme, plus a native settings window - with small installers per OS.

**Architecture:** `apps/tray` holds a Tauri v2 app: Rust core is a thin controller (spawn `miris` CLI, read `~/.miris/sessions` for state, TCP-probe/HTTP the laris overlay server on :8421, edit JSON/TOML config files); the web UI is one vanilla-TS settings form. Two backend prerequisites land first: a `laris-settings.json` override layer in packages/laris and a `note.path` record in packages/miris.

**Tech Stack:** Tauri v2 (tray-icon feature), Rust (ureq 3, serde_json, toml_edit, chrono, libc, dirs), vanilla TypeScript + Vite (template default), plugins: opener, notification.

## Global Constraints

- Stack: Tauri v2, identifier `dev.sammyj.voxis`, productName `VOXIS`, version `0.1.0` (spec: "mais funcional, leve e portável possível" - no frontend framework, no reqwest/tokio-heavy deps; ureq is blocking + tiny).
- Easy installation is a hard requirement: `npm run tauri build` must produce a native bundle (.dmg/.app on macOS) - Task 8 is part of DoD.
- UI copy in pt-BR ("Gravar reunião", "Configurações..."); all code/comments/identifiers in English. Plain hyphen `-` only, never em/en-dashes.
- Engines (laris/miris) stay macOS-only; Rust must still compile cross-platform (`#[cfg(unix)]` guards around signals).
- The tray NEVER deletes or rewrites engine state files it does not own (`recorder.pid`, `peers.json` are read-only; `orb-theme.json` only via POST /theme; `laris-settings.json` and `tray.json` are tray-owned).
- Engines offline -> menu items disabled or a notification explaining, never a crash (spec error handling).
- macOS GUI apps do not inherit shell PATH: every external binary is invoked via absolute path from `tray.json` config.
- Atomic writes (tmp + rename in same dir) for any file another process polls.
- laris `/theme` auth is a **query param** `?token=<token>`; token comes from `~/.config/voice-at/peers.json` under key `laris`.
- Python suites keep passing: laris 150 tests, miris 32 tests, always with `HF_HUB_DISABLE_XET=1`.

## Execution notes (codex-executor harness)

- **Reviewers:** python-reviewer for Tasks 1-2; there is no rust-reviewer subagent - for Tasks 4-6 dispatch a general-purpose subagent with an explicit Rust review prompt (blocking) + `agy -p` Gemini cross-review (advisory); typescript-reviewer for Task 7's frontend.
- **Network:** the Codex sandbox has no network. The orchestrator runs on the host: Task 3's `npm create tauri-app`, `npm install`, `cargo fetch`, and any `cargo add`. After that, `cargo build/test` works offline in the sandbox.
- **Verify on host:** never trust executor claims; run `cargo test`, `cargo build` and the Python suites on the host before each commit.

## File structure

```
packages/laris/laris/settings.py          # NEW - file>env>default override loader
packages/laris/laris/config.py            # MODIFIED - reads overrides
packages/laris/tests/test_settings.py     # NEW
packages/miris/miris/pipeline.py          # MODIFIED - writes note.path
apps/tray/                                # NEW Tauri app (template: vanilla-ts)
  index.html, src/main.ts, src/styles.css # settings window UI
  src-tauri/src/lib.rs                    # tray, menu, poll loop, actions
  src-tauri/src/miris.rs                  # recording state, start/stop, last note
  src-tauri/src/laris.rs                  # peer, liveness, theme API, daemon lifecycle
  src-tauri/src/settings.rs               # tray.json, laris-settings.json, miris config.toml
  src-tauri/src/commands.rs               # tauri commands for the settings window
  src-tauri/icons/tray-idle.png, tray-rec.png
brand/voxis-mark-recording.svg            # NEW - red-core variant
```

---

### Task 1: laris settings override layer (packages/laris)

**Files:**
- Create: `packages/laris/laris/settings.py`
- Modify: `packages/laris/laris/config.py`
- Modify: `packages/laris/tests/conftest.py` (create if missing)
- Test: `packages/laris/tests/test_settings.py`

**Interfaces:**
- Produces: `laris.settings.load_settings() -> dict[str, str]` (only KNOWN_KEYS, only str values, `{}` on missing/corrupt file); `laris.settings.settings_path() -> Path` (env `LARIS_SETTINGS_PATH` overrides `~/.config/voice-at/laris-settings.json`); `laris.settings.KNOWN_KEYS = ("ASSISTANT_MODE", "DICTATE_KEY", "STT_MODEL", "NOISE_REDUCTION")`. `config.MODE/DICTATE_KEY/NOISE_REDUCTION/STT_MODEL` resolve file > env > default at import time.
- Consumes: nothing new (stdlib only; settings.py must NOT import laris.config - config imports settings).

- [ ] **Step 1: Hermetic guard in conftest**

At the very top of `packages/laris/tests/conftest.py`, before any `laris` import (create the file if it does not exist; if it exists, prepend):

```python
import os

# Tests must never read the developer's real laris-settings.json - laris.config
# resolves overrides at import time, so this has to run before any laris import.
os.environ["LARIS_SETTINGS_PATH"] = "/nonexistent/laris-settings.json"
```

- [ ] **Step 2: Write the failing tests**

`packages/laris/tests/test_settings.py`:

```python
"""laris/settings.py - tray-written override file, file > env > default."""
import importlib
import json

import pytest

from laris import settings


@pytest.fixture
def fresh_config(monkeypatch):
    """Reload laris.config under the test's env, restore original afterwards."""
    from laris import config as config_module

    def _reload():
        return importlib.reload(config_module)

    yield _reload
    monkeypatch.undo()
    importlib.reload(config_module)


def test_missing_file_is_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("LARIS_SETTINGS_PATH", str(tmp_path / "nope.json"))
    assert settings.load_settings() == {}


def test_corrupt_file_is_empty(monkeypatch, tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("LARIS_SETTINGS_PATH", str(path))
    assert settings.load_settings() == {}


def test_non_dict_json_is_empty(monkeypatch, tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps(["DICTATE_KEY"]), encoding="utf-8")
    monkeypatch.setenv("LARIS_SETTINGS_PATH", str(path))
    assert settings.load_settings() == {}


def test_unknown_and_non_str_keys_filtered(monkeypatch, tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({
        "DICTATE_KEY": "f13",
        "EVIL_KEY": "x",
        "STT_MODEL": 42,
    }), encoding="utf-8")
    monkeypatch.setenv("LARIS_SETTINGS_PATH", str(path))
    assert settings.load_settings() == {"DICTATE_KEY": "f13"}


def test_file_beats_env_beats_default(monkeypatch, tmp_path, fresh_config):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"DICTATE_KEY": "f13"}), encoding="utf-8")
    monkeypatch.setenv("LARIS_SETTINGS_PATH", str(path))
    monkeypatch.setenv("DICTATE_KEY", "f5")
    monkeypatch.setenv("NOISE_REDUCTION", "off")
    cfg = fresh_config()
    assert cfg.DICTATE_KEY == "f13"        # file wins over env
    assert cfg.NOISE_REDUCTION == "off"    # env wins over default
    assert cfg.MODE == "ptt"               # default when neither set
```

- [ ] **Step 3: Run tests, verify failure**

```bash
cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_settings.py -q
```
Expected: FAIL / errors with `ModuleNotFoundError: laris.settings`.

- [ ] **Step 4: Implement `laris/settings.py`**

```python
"""Persisted settings override layer: file > env > default.
The VOXIS tray writes this file; laris reads it once at import (daemon start).
Live reload is deliberately out of scope - the tray restarts the daemon."""
import json
import os
from pathlib import Path

KNOWN_KEYS = ("ASSISTANT_MODE", "DICTATE_KEY", "STT_MODEL", "NOISE_REDUCTION")


def settings_path() -> Path:
    return Path(os.environ.get(
        "LARIS_SETTINGS_PATH", "~/.config/voice-at/laris-settings.json"
    )).expanduser()


def load_settings() -> dict[str, str]:
    """Known str-valued keys from the settings file; {} when missing/corrupt.
    Never writes - the file belongs to the tray app."""
    try:
        loaded = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {k: v for k, v in loaded.items()
            if k in KNOWN_KEYS and isinstance(v, str)}
```

- [ ] **Step 5: Wire `config.py`**

Replace the four env reads in `packages/laris/laris/config.py` (keep every other line, including comments, untouched):

```python
from laris.settings import load_settings

_FILE_OVERRIDES = load_settings()


def _setting(key: str, default: str) -> str:
    return _FILE_OVERRIDES.get(key, os.environ.get(key, default))


MODE = _setting("ASSISTANT_MODE", "ptt")  # "ptt" | "always_on"
DICTATE_KEY = _setting("DICTATE_KEY", "cmd_r")
```

and further down (preserving the existing q4 benchmark comment above STT_MODEL):

```python
NOISE_REDUCTION: str = _setting("NOISE_REDUCTION", "on")  # "on" | "off"
STT_MODEL: str = _setting("STT_MODEL", "mlx-community/whisper-large-v3-turbo-q4")
```

`STT_LANGUAGE` stays env-only (miris sets it programmatically; not a tray setting).

- [ ] **Step 6: Full suite green**

```bash
cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/ -q > /tmp/claude/laris-t1.log 2>&1; echo exit=$?
```
Expected: `exit=0`, 155 passed (150 + 5 new).

- [ ] **Step 7: Commit**

```bash
cd ~/code/voxis && git add packages/laris && git commit -m "feat(laris): settings file override layer (file > env > default)"
```

---

### Task 2: miris records the vault note path (packages/miris)

**Files:**
- Modify: `packages/miris/miris/pipeline.py` (the `return vault.save_note(...)` tail of `process_session`)
- Test: `packages/miris/tests/test_pipeline.py` (add one test, reusing the existing happy-path fixture/arrange block in that file)

**Interfaces:**
- Produces: `<session_dir>/note.path` - UTF-8 text file with the absolute vault note path. Task 4's `miris::last_note` reads it.

- [ ] **Step 1: Write the failing test**

Add to `packages/miris/tests/test_pipeline.py`, copying the arrange section (cfg, session dir, WAV/transcript fixtures, LLM stub) of the existing happy-path `process_session` test in that same file:

```python
def test_process_session_records_note_path(...same fixtures as the happy-path test...):
    note = pipeline.process_session(cfg, session)
    assert (session / "note.path").read_text(encoding="utf-8") == str(note)
```

- [ ] **Step 2: Run it, verify failure**

```bash
cd ~/code/voxis/packages/miris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_pipeline.py -q
```
Expected: FAIL with `FileNotFoundError` on `note.path`.

- [ ] **Step 3: Implement**

In `packages/miris/miris/pipeline.py`, change the end of `process_session`:

```python
    note = vault.save_note(cfg, notes, transcript, session_dir.name)
    # the VOXIS tray reads this to open the last note without parsing CLI stdout
    (session_dir / "note.path").write_text(str(note), encoding="utf-8")
    return note
```

- [ ] **Step 4: Full suite green**

```bash
cd ~/code/voxis/packages/miris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/ -q > /tmp/claude/miris-t2.log 2>&1; echo exit=$?
```
Expected: `exit=0`, 33 passed.

- [ ] **Step 5: Commit**

```bash
cd ~/code/voxis && git add packages/miris && git commit -m "feat(miris): record vault note path in session dir for the tray"
```

---

### Task 3: Tauri scaffold, brand icons, static tray (orchestrator-heavy: needs network)

**Files:**
- Create: `apps/tray/` via `create-tauri-app` (vanilla-ts template)
- Create: `brand/voxis-mark-recording.svg`
- Create: `apps/tray/src-tauri/icons/tray-idle.png`, `tray-rec.png`
- Modify: `apps/tray/src-tauri/tauri.conf.json`, `Cargo.toml`, `src/lib.rs`, `src/main.rs`

**Interfaces:**
- Produces: a building Tauri app whose tray shows the VOXIS mark with a menu containing only "Sair"; `icons/tray-idle.png` (template/mono) and `tray-rec.png` (colored) that Tasks 6 embeds via `include_bytes!`.

- [ ] **Step 1: Scaffold (host, network)**

```bash
cd ~/code/voxis && mkdir -p apps && cd apps && \
  npm create tauri-app@latest tray -- --identifier dev.sammyj.voxis --template vanilla-ts --manager npm --yes
cd tray && npm install
```
If the flag set differs in the installed create-tauri-app version, answer the prompts: name `tray`, identifier `dev.sammyj.voxis`, frontend `TypeScript`, template `Vanilla`, manager `npm`.

- [ ] **Step 2: Recording-variant SVG**

`brand/voxis-mark-recording.svg` = copy of `brand/voxis-mark.svg` with the center circle swapped for a red recording dot (last line before `</svg>`):

```xml
<circle cx="44" cy="44" r="8.0" fill="#e5484d"/>
```

- [ ] **Step 3: Render tray PNGs and app icon (host, network for cargo install)**

```bash
cargo install resvg --locked   # skip if `resvg --help` already works
cd ~/code/voxis
resvg brand/voxis-mark.svg apps/tray/src-tauri/icons/tray-idle.png --width 44 --height 44
resvg brand/voxis-mark-recording.svg apps/tray/src-tauri/icons/tray-rec.png --width 44 --height 44
resvg brand/voxis-mark.svg /tmp/claude/voxis-1024.png --width 1024 --height 1024
cd apps/tray && npm run tauri icon /tmp/claude/voxis-1024.png
```

- [ ] **Step 4: Configure `tauri.conf.json`**

Edit `apps/tray/src-tauri/tauri.conf.json`: set `"productName": "VOXIS"`, `"version": "0.1.0"`, and empty the startup windows (settings window is created on demand in Task 7):

```json
"app": {
  "windows": [],
  "security": { "csp": null }
}
```

- [ ] **Step 5: Cargo deps**

In `apps/tray/src-tauri/Cargo.toml` (run `cargo fetch` on the host afterwards):

```toml
[dependencies]
tauri = { version = "2", features = ["tray-icon", "image-png"] }
tauri-plugin-opener = "2"
tauri-plugin-notification = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
ureq = { version = "3", features = ["json"] }
chrono = "0.4"
toml_edit = "0.22"
dirs = "6"

[target.'cfg(unix)'.dependencies]
libc = "0.2"

[dev-dependencies]
tempfile = "3"
```

- [ ] **Step 6: Minimal tray in `lib.rs`**

Replace `apps/tray/src-tauri/src/lib.rs`:

```rust
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            let quit = MenuItem::with_id(app, "quit", "Sair", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&quit])?;
            let icon = tauri::image::Image::from_bytes(include_bytes!("../icons/tray-idle.png"))?;
            TrayIconBuilder::with_id("voxis")
                .icon(icon)
                .icon_as_template(true)
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| {
                    if event.id().as_ref() == "quit" {
                        app.exit(0);
                    }
                })
                .build(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

`src/main.rs` stays as the template generated it (calls `tray_lib::run()` - keep whatever lib name the template chose, but rename the crate lib to `voxis_tray` only if the template name is unusable).

- [ ] **Step 7: Compile check**

```bash
cd ~/code/voxis/apps/tray/src-tauri && cargo build 2>&1 | tail -5; echo exit=$?
```
Expected: `exit=0`.

- [ ] **Step 8: Manual smoke (user or orchestrator)**

`cd ~/code/voxis/apps/tray && npm run tauri dev` - VOXIS mark appears in the macOS menu bar, menu has "Sair", clicking quits. No Dock icon (Accessory policy).

- [ ] **Step 9: Commit**

```bash
cd ~/code/voxis && git add apps/tray brand/voxis-mark-recording.svg && \
  git commit -m "feat(tray): Tauri v2 scaffold with VOXIS tray icon and quit menu"
```

---

### Task 4: miris integration module (Rust, TDD)

**Files:**
- Create: `apps/tray/src-tauri/src/miris.rs`
- Modify: `apps/tray/src-tauri/src/lib.rs` (add `mod miris;`)

**Interfaces:**
- Produces:
  - `pub enum MirisStatus { Idle, Recording { session: String, pid: i32 } }`
  - `pub fn status(sessions_dir: &Path) -> MirisStatus`
  - `pub fn recording_minutes(session: &str, now: chrono::DateTime<chrono::Local>) -> Option<i64>`
  - `pub fn last_note(sessions_dir: &Path) -> Option<PathBuf>`
  - `pub fn start(miris_bin: &str) -> Result<(), String>`
  - `pub fn stop(miris_bin: &str) -> Result<PathBuf, String>` (BLOCKING - minutes on long meetings; caller threads it)
  - `pub fn parse_note_path(stdout: &str) -> Option<PathBuf>`
- Consumes: session-dir layout from miris (`<sessions>/<%Y%m%d-%H%M%S>/recorder.pid`, `note.path` from Task 2; `miris stop` prints `note: <path>`).

- [ ] **Step 1: Write failing tests (bottom of `miris.rs` as `#[cfg(test)] mod tests`)**

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn session(dir: &std::path::Path, name: &str, pid: Option<i32>) -> std::path::PathBuf {
        let s = dir.join(name);
        fs::create_dir_all(&s).unwrap();
        if let Some(p) = pid {
            fs::write(s.join("recorder.pid"), p.to_string()).unwrap();
        }
        s
    }

    #[test]
    fn status_idle_when_dir_missing_or_empty() {
        let tmp = tempfile::tempdir().unwrap();
        assert_eq!(status(&tmp.path().join("nope")), MirisStatus::Idle);
        assert_eq!(status(tmp.path()), MirisStatus::Idle);
    }

    #[test]
    fn status_recording_with_live_pid() {
        let tmp = tempfile::tempdir().unwrap();
        let me = std::process::id() as i32; // our own pid is always alive
        session(tmp.path(), "20260716-100000", Some(me));
        assert_eq!(
            status(tmp.path()),
            MirisStatus::Recording { session: "20260716-100000".into(), pid: me }
        );
    }

    #[test]
    fn status_skips_dead_and_corrupt_pids_without_deleting_them() {
        let tmp = tempfile::tempdir().unwrap();
        let dead = session(tmp.path(), "20260716-110000", Some(99999999));
        let corrupt = session(tmp.path(), "20260716-120000", None);
        fs::write(corrupt.join("recorder.pid"), "not-a-pid").unwrap();
        assert_eq!(status(tmp.path()), MirisStatus::Idle);
        // read-only contract: stale-pidfile cleanup belongs to the miris CLI
        assert!(dead.join("recorder.pid").exists());
        assert!(corrupt.join("recorder.pid").exists());
    }

    #[test]
    fn status_newest_live_session_wins() {
        let tmp = tempfile::tempdir().unwrap();
        let me = std::process::id() as i32;
        session(tmp.path(), "20260716-100000", Some(me));
        session(tmp.path(), "20260716-200000", Some(me));
        match status(tmp.path()) {
            MirisStatus::Recording { session, .. } => assert_eq!(session, "20260716-200000"),
            other => panic!("expected recording, got {other:?}"),
        }
    }

    #[test]
    fn recording_minutes_from_session_name() {
        let now = chrono::Local.with_ymd_and_hms(2026, 7, 16, 10, 12, 0).unwrap();
        assert_eq!(recording_minutes("20260716-100000", now), Some(12));
        assert_eq!(recording_minutes("garbage", now), None);
    }

    #[test]
    fn last_note_newest_existing_target() {
        let tmp = tempfile::tempdir().unwrap();
        let target = tmp.path().join("note.md");
        fs::write(&target, "x").unwrap();
        let old = session(tmp.path(), "20260716-100000", None);
        fs::write(old.join("note.path"), target.to_string_lossy().as_bytes()).unwrap();
        let newer_without = session(tmp.path(), "20260716-200000", None);
        let _ = newer_without; // newest session has no note.path -> falls back to older
        assert_eq!(last_note(tmp.path()), Some(target));
    }

    #[test]
    fn last_note_none_when_target_missing() {
        let tmp = tempfile::tempdir().unwrap();
        let s = session(tmp.path(), "20260716-100000", None);
        fs::write(s.join("note.path"), "/nonexistent/note.md").unwrap();
        assert_eq!(last_note(tmp.path()), None);
    }

    #[test]
    fn parse_note_path_last_note_line() {
        let out = "recording finished, processing...\nnote: /vault/x.md\n";
        assert_eq!(parse_note_path(out), Some(std::path::PathBuf::from("/vault/x.md")));
        assert_eq!(parse_note_path("idle\n"), None);
    }

    #[test]
    fn run_cli_captures_stdout_and_stderr() {
        assert_eq!(run_cli("echo", "start").unwrap().trim(), "start");
        assert!(run_cli("/nonexistent-bin-xyz", "start").is_err());
    }
}
```

Add `use chrono::TimeZone;` inside the test module for `with_ymd_and_hms`.

- [ ] **Step 2: Run tests, verify failure**

```bash
cd ~/code/voxis/apps/tray/src-tauri && cargo test miris 2>&1 | tail -5
```
Expected: compile error (module functions missing).

- [ ] **Step 3: Implement `miris.rs`**

```rust
//! MIRIS integration. Recording state is read straight from the sessions dir
//! (running the Python CLI costs seconds of imports - too heavy for a 2s
//! poll); start/stop still go through the CLI binary.

use std::path::{Path, PathBuf};
use std::process::Command;

#[derive(Debug, Clone, PartialEq)]
pub enum MirisStatus {
    Idle,
    Recording { session: String, pid: i32 },
}

fn session_dirs_newest_first(sessions_dir: &Path) -> Vec<PathBuf> {
    let Ok(rd) = std::fs::read_dir(sessions_dir) else { return Vec::new() };
    let mut dirs: Vec<PathBuf> = rd
        .filter_map(|e| e.ok().map(|e| e.path()))
        .filter(|p| p.is_dir())
        .collect();
    dirs.sort(); // names are %Y%m%d-%H%M%S, lexicographic == chronological
    dirs.reverse();
    dirs
}

/// Newest session dir with a live recorder.pid. Read-only: stale pidfile
/// cleanup belongs to the miris CLI, never the tray.
pub fn status(sessions_dir: &Path) -> MirisStatus {
    for dir in session_dirs_newest_first(sessions_dir) {
        let Ok(raw) = std::fs::read_to_string(dir.join("recorder.pid")) else { continue };
        let Ok(pid) = raw.trim().parse::<i32>() else { continue };
        if pid_alive(pid) {
            let session = dir
                .file_name()
                .map(|n| n.to_string_lossy().into_owned())
                .unwrap_or_default();
            return MirisStatus::Recording { session, pid };
        }
    }
    MirisStatus::Idle
}

#[cfg(unix)]
fn pid_alive(pid: i32) -> bool {
    // ponytail: signal-0 probe; EPERM can't happen (recorder runs as our user)
    unsafe { libc::kill(pid, 0) == 0 }
}

#[cfg(not(unix))]
fn pid_alive(_pid: i32) -> bool {
    false // engines are macOS-only today
}

/// Minutes elapsed since the session started (its dir name is the timestamp).
pub fn recording_minutes(session: &str, now: chrono::DateTime<chrono::Local>) -> Option<i64> {
    let naive = chrono::NaiveDateTime::parse_from_str(session, "%Y%m%d-%H%M%S").ok()?;
    let started = naive.and_local_timezone(chrono::Local).single()?;
    Some((now - started).num_minutes().max(0))
}

/// Newest session with a note.path record whose target still exists.
pub fn last_note(sessions_dir: &Path) -> Option<PathBuf> {
    for dir in session_dirs_newest_first(sessions_dir) {
        let Ok(raw) = std::fs::read_to_string(dir.join("note.path")) else { continue };
        let path = PathBuf::from(raw.trim());
        if path.exists() {
            return Some(path);
        }
    }
    None
}

/// `miris start` - fast (the recorder detaches itself).
pub fn start(miris_bin: &str) -> Result<(), String> {
    run_cli(miris_bin, "start").map(|_| ())
}

/// `miris stop` - BLOCKING: runs transcription + LLM, minutes on long
/// meetings. Callers must run it off the main thread.
pub fn stop(miris_bin: &str) -> Result<PathBuf, String> {
    let stdout = run_cli(miris_bin, "stop")?;
    parse_note_path(&stdout)
        .ok_or_else(|| format!("no note path in miris stop output:\n{stdout}"))
}

pub fn parse_note_path(stdout: &str) -> Option<PathBuf> {
    stdout
        .lines()
        .rev()
        .find_map(|l| l.strip_prefix("note: "))
        .map(|p| PathBuf::from(p.trim()))
}

fn run_cli(miris_bin: &str, arg: &str) -> Result<String, String> {
    let out = Command::new(miris_bin)
        .arg(arg)
        .output()
        .map_err(|e| format!("failed to run {miris_bin}: {e}"))?;
    if out.status.success() {
        Ok(String::from_utf8_lossy(&out.stdout).into_owned())
    } else {
        let stderr = String::from_utf8_lossy(&out.stderr);
        let tail: Vec<&str> = stderr.lines().rev().take(3).collect();
        Err(tail.into_iter().rev().collect::<Vec<_>>().join("\n"))
    }
}
```

Add `mod miris;` to `lib.rs`. Prefix the `run_cli` test bin with a cfg guard if Windows CI ever runs it (not needed now: tests run on macOS).

- [ ] **Step 4: Tests green**

```bash
cd ~/code/voxis/apps/tray/src-tauri && cargo test 2>&1 | tail -5; echo exit=$?
```
Expected: `exit=0`, 9 tests passed.

- [ ] **Step 5: Commit**

```bash
cd ~/code/voxis && git add apps/tray && git commit -m "feat(tray): miris integration - filesystem status, start/stop, last note"
```

---

### Task 5: laris + settings modules (Rust, TDD)

**Files:**
- Create: `apps/tray/src-tauri/src/laris.rs`
- Create: `apps/tray/src-tauri/src/settings.rs`
- Modify: `apps/tray/src-tauri/src/lib.rs` (add `mod laris; mod settings;`)

**Interfaces:**
- Produces (laris.rs):
  - `pub struct LarisPeer { pub url: String, pub token: String }`
  - `pub fn read_peer(path: &Path) -> Option<LarisPeer>` (peers.json, key `laris`)
  - `pub fn alive(url: &str) -> bool` (TCP connect, 300ms timeout)
  - `pub fn get_theme(peer: &LarisPeer) -> Result<serde_json::Value, String>` / `pub fn set_theme(peer: &LarisPeer, updates: serde_json::Value) -> Result<serde_json::Value, String>` (query-param token)
  - `pub struct LarisDaemon` with `new(laris_dir: PathBuf)`, `spawn(&mut self) -> Result<(), String>`, `stop(&mut self)`, `owns_running(&mut self) -> bool`
- Produces (settings.rs):
  - `pub fn config_dir() -> PathBuf` (`~/.config/voice-at`)
  - `pub fn laris_settings_path() -> PathBuf` (`config_dir()/laris-settings.json`)
  - `pub fn read_json_map(path: &Path) -> serde_json::Map<String, serde_json::Value>`
  - `pub fn write_json_atomic(path: &Path, value: &serde_json::Value) -> Result<(), String>`
  - `pub struct TrayConfig { pub miris_bin: String, pub laris_dir: String, pub miris_home: String }` + `pub fn load_tray_config() -> TrayConfig` (`config_dir()/tray.json`, defaults below)
  - `pub fn read_miris_config(path: &Path) -> Result<serde_json::Value, String>` -> `{"vault_root", "llm_command", "categories"}`
  - `pub fn update_miris_config(path: &Path, vault_root: &str, llm_command: &[String], categories: &[(String, String)]) -> Result<(), String>` (toml_edit, comments preserved)
- Consumes: `MirisStatus` etc. not needed here; peers.json shape `{"laris": {"url": "http://127.0.0.1:8421", "token": "<hex>"}}`.

- [ ] **Step 1: Write failing tests**

`laris.rs` test module:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn read_peer_happy_path() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("peers.json");
        fs::write(&p, r#"{"laris": {"url": "http://127.0.0.1:8421", "token": "abc"}}"#).unwrap();
        let peer = read_peer(&p).unwrap();
        assert_eq!(peer.url, "http://127.0.0.1:8421");
        assert_eq!(peer.token, "abc");
    }

    #[test]
    fn read_peer_missing_or_corrupt_is_none() {
        let tmp = tempfile::tempdir().unwrap();
        assert!(read_peer(&tmp.path().join("nope.json")).is_none());
        let p = tmp.path().join("bad.json");
        fs::write(&p, "{oops").unwrap();
        assert!(read_peer(&p).is_none());
        fs::write(&p, r#"{"laris": {"url": 1}}"#).unwrap();
        assert!(read_peer(&p).is_none());
    }

    #[test]
    fn alive_true_for_bound_listener_false_otherwise() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        assert!(alive(&format!("http://127.0.0.1:{port}")));
        drop(listener);
        assert!(!alive(&format!("http://127.0.0.1:{port}")));
        assert!(!alive("not-a-url"));
    }
}
```

`settings.rs` test module:

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn read_json_map_missing_corrupt_or_non_object_is_empty() {
        let tmp = tempfile::tempdir().unwrap();
        assert!(read_json_map(&tmp.path().join("nope.json")).is_empty());
        let p = tmp.path().join("bad.json");
        fs::write(&p, "[1,2]").unwrap();
        assert!(read_json_map(&p).is_empty());
    }

    #[test]
    fn write_json_atomic_roundtrip_no_tmp_leftover() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("deep/dir/s.json");
        let value = serde_json::json!({"DICTATE_KEY": "f13"});
        write_json_atomic(&p, &value).unwrap();
        assert_eq!(read_json_map(&p).get("DICTATE_KEY").unwrap(), "f13");
        let leftovers: Vec<_> = fs::read_dir(p.parent().unwrap()).unwrap()
            .filter_map(|e| e.ok())
            .filter(|e| e.file_name().to_string_lossy().ends_with(".tmp"))
            .collect();
        assert!(leftovers.is_empty());
    }

    #[test]
    fn tray_config_defaults() {
        let cfg = TrayConfig::default();
        assert!(cfg.miris_bin.ends_with("/.local/bin/miris"));
        assert!(cfg.laris_dir.ends_with("/code/voxis/packages/laris"));
        assert!(cfg.miris_home.ends_with("/.miris"));
    }

    const SAMPLE_TOML: &str = "\
vault_root = \"~/vault\"
inbox = \"inbox\"
# swapping provider = edit this line, never code
llm_command = [\"agy\", \"--model\", \"Gemini 3.5 Flash (Medium)\", \"-p\"]

[categories]
trabalho = \"work-notes\"
";

    #[test]
    fn miris_config_read() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("config.toml");
        fs::write(&p, SAMPLE_TOML).unwrap();
        let cfg = read_miris_config(&p).unwrap();
        assert_eq!(cfg["vault_root"], "~/vault");
        assert_eq!(cfg["llm_command"][3], "-p");
        assert_eq!(cfg["categories"]["trabalho"], "work-notes");
    }

    #[test]
    fn miris_config_update_preserves_comments() {
        let tmp = tempfile::tempdir().unwrap();
        let p = tmp.path().join("config.toml");
        fs::write(&p, SAMPLE_TOML).unwrap();
        update_miris_config(
            &p,
            "~/vault2",
            &["agy".into(), "-p".into()],
            &[("entrevistas".into(), "work-notes/interviews".into())],
        ).unwrap();
        let raw = fs::read_to_string(&p).unwrap();
        assert!(raw.contains("# swapping provider"));
        assert!(raw.contains("vault_root = \"~/vault2\""));
        assert!(raw.contains("entrevistas"));
        assert!(!raw.contains("trabalho")); // categories table fully replaced
    }
}
```

- [ ] **Step 2: Run tests, verify failure**

```bash
cd ~/code/voxis/apps/tray/src-tauri && cargo test 2>&1 | tail -5
```
Expected: compile errors.

- [ ] **Step 3: Implement `laris.rs`**

```rust
//! LARIS integration: peer discovery, liveness probe, theme API, and the
//! lifecycle of a tray-spawned dictation daemon. An externally started
//! daemon is detected via alive() but never killed by the tray.

use std::path::{Path, PathBuf};
use std::process::{Child, Command};
use std::time::Duration;

#[derive(Debug, Clone, PartialEq)]
pub struct LarisPeer {
    pub url: String,
    pub token: String,
}

/// peers.json is written by the laris daemon on boot: {"laris": {url, token}}.
pub fn read_peer(path: &Path) -> Option<LarisPeer> {
    let raw = std::fs::read_to_string(path).ok()?;
    let json: serde_json::Value = serde_json::from_str(&raw).ok()?;
    let laris = json.get("laris")?;
    Some(LarisPeer {
        url: laris.get("url")?.as_str()?.to_owned(),
        token: laris.get("token")?.as_str()?.to_owned(),
    })
}

/// TCP probe on the overlay port - cheap enough for the 2s poll tick.
pub fn alive(url: &str) -> bool {
    url.strip_prefix("http://")
        .and_then(|a| a.trim_end_matches('/').parse().ok())
        .map(|addr| {
            std::net::TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
        })
        .unwrap_or(false)
}

pub fn get_theme(peer: &LarisPeer) -> Result<serde_json::Value, String> {
    let mut res = ureq::get(format!("{}/theme?token={}", peer.url, peer.token))
        .call()
        .map_err(|e| e.to_string())?;
    res.body_mut().read_json().map_err(|e| e.to_string())
}

pub fn set_theme(peer: &LarisPeer, updates: serde_json::Value) -> Result<serde_json::Value, String> {
    let mut res = ureq::post(format!("{}/theme?token={}", peer.url, peer.token))
        .send_json(&updates)
        .map_err(|e| e.to_string())?;
    res.body_mut().read_json().map_err(|e| e.to_string())
}

pub struct LarisDaemon {
    child: Option<Child>,
    laris_dir: PathBuf,
}

impl LarisDaemon {
    pub fn new(laris_dir: PathBuf) -> Self {
        Self { child: None, laris_dir }
    }

    pub fn owns_running(&mut self) -> bool {
        match self.child.as_mut().map(|c| c.try_wait()) {
            Some(Ok(None)) => true, // still running
            _ => {
                self.child = None; // exited, errored, or never spawned
                false
            }
        }
    }

    pub fn spawn(&mut self) -> Result<(), String> {
        let python = self.laris_dir.join(".venv/bin/python");
        let child = Command::new(&python)
            .args(["-m", "laris"])
            .current_dir(&self.laris_dir)
            .spawn()
            .map_err(|e| format!("{}: {e}", python.display()))?;
        self.child = Some(child);
        Ok(())
    }

    /// SIGTERM first (laris tears down overlay + keyboard listener), SIGKILL
    /// after 3s if it hangs.
    pub fn stop(&mut self) {
        let Some(mut child) = self.child.take() else { return };
        #[cfg(unix)]
        unsafe {
            libc::kill(child.id() as i32, libc::SIGTERM);
        }
        for _ in 0..30 {
            if let Ok(Some(_)) = child.try_wait() {
                return;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill();
        let _ = child.wait();
    }
}
```

- [ ] **Step 4: Implement `settings.rs`**

```rust
//! Config files the tray owns or edits: tray.json + laris-settings.json
//! (owned, JSON, atomic writes) and miris config.toml (edited via toml_edit
//! so hand-written comments survive).

use std::path::{Path, PathBuf};

fn home() -> PathBuf {
    dirs::home_dir().expect("no home dir")
}

pub fn config_dir() -> PathBuf {
    home().join(".config/voice-at")
}

pub fn laris_settings_path() -> PathBuf {
    config_dir().join("laris-settings.json")
}

pub fn read_json_map(path: &Path) -> serde_json::Map<String, serde_json::Value> {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|raw| serde_json::from_str::<serde_json::Value>(&raw).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

/// tmp + rename in the same dir: laris reads this file from another process.
pub fn write_json_atomic(path: &Path, value: &serde_json::Value) -> Result<(), String> {
    let parent = path.parent().ok_or("path has no parent")?;
    std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let name = path.file_name().unwrap_or_default().to_string_lossy();
    let tmp = parent.join(format!(".{name}.tmp"));
    let body = serde_json::to_string_pretty(value).map_err(|e| e.to_string())?;
    std::fs::write(&tmp, body).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, path).map_err(|e| e.to_string())
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct TrayConfig {
    pub miris_bin: String,
    pub laris_dir: String,
    pub miris_home: String,
}

impl Default for TrayConfig {
    fn default() -> Self {
        // GUI apps don't inherit shell PATH - absolute paths only
        let h = home().to_string_lossy().into_owned();
        Self {
            miris_bin: format!("{h}/.local/bin/miris"),
            laris_dir: format!("{h}/code/voxis/packages/laris"),
            miris_home: format!("{h}/.miris"),
        }
    }
}

pub fn load_tray_config() -> TrayConfig {
    let path = config_dir().join("tray.json");
    std::fs::read_to_string(&path)
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}

pub fn read_miris_config(path: &Path) -> Result<serde_json::Value, String> {
    let raw = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let doc: toml_edit::DocumentMut = raw.parse().map_err(|e: toml_edit::TomlError| e.to_string())?;
    let vault_root = doc.get("vault_root").and_then(|v| v.as_str()).unwrap_or("~/vault").to_owned();
    let llm_command: Vec<String> = doc
        .get("llm_command")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
        .unwrap_or_default();
    let categories: serde_json::Map<String, serde_json::Value> = doc
        .get("categories")
        .and_then(|v| v.as_table())
        .map(|t| {
            t.iter()
                .filter_map(|(k, v)| {
                    v.as_str().map(|s| (k.to_owned(), serde_json::Value::String(s.to_owned())))
                })
                .collect()
        })
        .unwrap_or_default();
    Ok(serde_json::json!({
        "vault_root": vault_root,
        "llm_command": llm_command,
        "categories": categories,
    }))
}

pub fn update_miris_config(
    path: &Path,
    vault_root: &str,
    llm_command: &[String],
    categories: &[(String, String)],
) -> Result<(), String> {
    let raw = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let mut doc: toml_edit::DocumentMut = raw.parse().map_err(|e: toml_edit::TomlError| e.to_string())?;
    doc["vault_root"] = toml_edit::value(vault_root);
    let mut arr = toml_edit::Array::new();
    for part in llm_command {
        arr.push(part.as_str());
    }
    doc["llm_command"] = toml_edit::value(arr);
    let mut table = toml_edit::Table::new();
    for (key, folder) in categories {
        table[key.as_str()] = toml_edit::value(folder.as_str());
    }
    doc["categories"] = toml_edit::Item::Table(table);
    std::fs::write(path, doc.to_string()).map_err(|e| e.to_string())
}
```

Add `mod laris; mod settings;` to `lib.rs`.

- [ ] **Step 5: Tests green**

```bash
cd ~/code/voxis/apps/tray/src-tauri && cargo test 2>&1 | tail -5; echo exit=$?
```
Expected: `exit=0`, 17 tests passed (9 from Task 4 + 8 new).

- [ ] **Step 6: Commit**

```bash
cd ~/code/voxis && git add apps/tray && git commit -m "feat(tray): laris peer/theme/daemon and config-file modules"
```

---

### Task 6: dynamic tray menu, poll loop, actions

**Files:**
- Modify: `apps/tray/src-tauri/src/lib.rs` (full rewrite below)

**Interfaces:**
- Consumes: everything from Tasks 4-5 exactly as declared there.
- Produces: `pub struct AppState { pub config: settings::TrayConfig, pub daemon: Mutex<laris::LarisDaemon>, pub processing: AtomicBool }` managed via `app.manage(...)`; `fn show_settings_placeholder` replaced in Task 7 by `commands::show_settings_window(&AppHandle)`.

- [ ] **Step 1: Rewrite `lib.rs`**

```rust
mod laris;
mod miris;
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

pub struct AppState {
    pub config: settings::TrayConfig,
    pub daemon: Mutex<laris::LarisDaemon>,
    pub processing: AtomicBool,
}

#[derive(Debug, Clone, PartialEq, Default)]
struct Snapshot {
    recording: Option<(String, i64)>, // (session id, minutes)
    processing: bool,
    laris_alive: bool,
    hands_free: bool,
    has_last_note: bool,
    theme: Option<(String, String, String)>, // (archetype, palette, position)
}

fn peers_path() -> PathBuf {
    settings::config_dir().join("peers.json")
}

fn sessions_dir(state: &AppState) -> PathBuf {
    PathBuf::from(&state.config.miris_home).join("sessions")
}

fn take_snapshot(state: &AppState) -> Snapshot {
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
    // ponytail: theme fetched every tick while laris is up - localhost HTTP,
    // negligible; cache only if it ever shows up in a profile
    let theme = peer
        .filter(|_| laris_alive)
        .and_then(|p| laris::get_theme(&p).ok())
        .and_then(|body| {
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
        recording,
        processing: state.processing.load(Ordering::SeqCst),
        laris_alive,
        hands_free,
        has_last_note: miris::last_note(&sessions).is_some(),
        theme,
    }
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
    let dictation =
        CheckMenuItem::with_id(app, "dictation", "Ditado", true, snap.laris_alive, None::<&str>)?;
    let hands_free = CheckMenuItem::with_id(
        app, "hands_free", "Hands-free", snap.laris_alive, snap.hands_free, None::<&str>,
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
    let (bytes, template): (&[u8], bool) = if recording {
        (include_bytes!("../icons/tray-rec.png"), false)
    } else {
        (include_bytes!("../icons/tray-idle.png"), true)
    };
    if let Ok(img) = tauri::image::Image::from_bytes(bytes) {
        let _ = tray.set_icon_as_template(template);
        let _ = tray.set_icon(Some(img));
    }
}

fn notify(app: &AppHandle, body: &str) {
    let _ = app.notification().builder().title("VOXIS").body(body).show();
}

fn handle_menu(app: &AppHandle, id: &str) {
    let state = app.state::<AppState>();
    match id {
        "quit" => {
            state.daemon.lock().unwrap().stop();
            app.exit(0);
        }
        "settings" => show_settings_placeholder(app),
        "miris_start" => {
            if let Err(e) = miris::start(&state.config.miris_bin) {
                notify(app, &format!("Falha ao iniciar gravação: {e}"));
            }
        }
        "miris_stop" => {
            let app2 = app.clone();
            let bin = state.config.miris_bin.clone();
            state.processing.store(true, Ordering::SeqCst);
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
            let mut daemon = state.daemon.lock().unwrap();
            if daemon.owns_running() {
                daemon.stop();
            } else {
                let external = laris::read_peer(&peers_path())
                    .map(|p| laris::alive(&p.url))
                    .unwrap_or(false);
                if external {
                    // the tray never kills a daemon it didn't start
                    notify(app, "Ditado foi iniciado fora do VOXIS - encerre-o por lá");
                } else if let Err(e) = daemon.spawn() {
                    notify(app, &format!("Falha ao iniciar ditado: {e}"));
                }
            }
        }
        "hands_free" => {
            let path = settings::laris_settings_path();
            let mut map = settings::read_json_map(&path);
            let now_on = map.get("ASSISTANT_MODE").and_then(|v| v.as_str()) == Some("always_on");
            let next = if now_on { "ptt" } else { "always_on" };
            map.insert("ASSISTANT_MODE".into(), serde_json::Value::String(next.into()));
            if let Err(e) = settings::write_json_atomic(&path, &serde_json::Value::Object(map)) {
                notify(app, &format!("Falha ao salvar: {e}"));
                return;
            }
            // settings load at daemon start only - restart our own daemon to apply
            let mut daemon = state.daemon.lock().unwrap();
            if daemon.owns_running() {
                daemon.stop();
                if let Err(e) = daemon.spawn() {
                    notify(app, &format!("Falha ao reiniciar ditado: {e}"));
                }
            }
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

// Task 7 replaces this with commands::show_settings_window
fn show_settings_placeholder(app: &AppHandle) {
    notify(app, "Configurações chegam na próxima tarefa");
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            let config = settings::load_tray_config();
            let daemon = laris::LarisDaemon::new(PathBuf::from(&config.laris_dir));
            app.manage(AppState {
                config,
                daemon: Mutex::new(daemon),
                processing: AtomicBool::new(false),
            });

            let snap = take_snapshot(&app.state::<AppState>());
            let menu = build_menu(app.handle(), &snap)?;
            let icon = tauri::image::Image::from_bytes(include_bytes!("../icons/tray-idle.png"))?;
            let tray = TrayIconBuilder::with_id("voxis")
                .icon(icon)
                .icon_as_template(true)
                .menu(&menu)
                .show_menu_on_left_click(true)
                .on_menu_event(|app, event| handle_menu(app, event.id().as_ref()))
                .build(app)?;
            set_tray_icon(&tray, snap.recording.is_some());

            // poll loop: snapshot off the main thread, menu mutations on it
            // (macOS requires menu construction on the main thread)
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let mut last = snap;
                loop {
                    std::thread::sleep(Duration::from_secs(2));
                    let current = take_snapshot(&handle.state::<AppState>());
                    if current == last {
                        continue;
                    }
                    let recording_changed =
                        current.recording.is_some() != last.recording.is_some();
                    last = current.clone();
                    let handle2 = handle.clone();
                    let _ = handle.run_on_main_thread(move || {
                        if let Some(tray) = handle2.tray_by_id("voxis") {
                            if let Ok(menu) = build_menu(&handle2, &current) {
                                let _ = tray.set_menu(Some(menu));
                            }
                            if recording_changed {
                                set_tray_icon(&tray, current.recording.is_some());
                            }
                        }
                    });
                }
            });
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

- [ ] **Step 2: Compile + existing tests green**

```bash
cd ~/code/voxis/apps/tray/src-tauri && cargo test 2>&1 | tail -5; echo exit=$?
```
Expected: `exit=0`, 17 passed (this task is glue - validated by smoke, not unit tests).

- [ ] **Step 3: Manual smoke with the user (macOS)**

`npm run tauri dev`, then walk the matrix:
1. Icon idle (mono template) with laris/miris stopped; "Última nota" enabled (sessions exist), theme submenu disabled.
2. "Ditado" toggle on -> orb daemon boots, checkmark on next tick, theme submenu enables; switch palette -> orb changes live (overlay polls the file).
3. "Gravar reunião" -> icon flips to red-core variant, item becomes "Parar gravação (0 min)".
4. "Parar gravação" -> "Processando reunião..." disabled item, then notification "Nota salva: ...", "Última nota" opens it.
5. "Hands-free" toggle -> daemon restarts with ASSISTANT_MODE=always_on (verify `~/.config/voice-at/laris-settings.json`).
6. "Sair" -> tray-owned laris daemon dies too (`pgrep -f "python -m laris"` empty).

- [ ] **Step 4: Commit**

```bash
cd ~/code/voxis && git add apps/tray && git commit -m "feat(tray): dynamic menu, 2s poll loop, recording icon states and actions"
```

---

### Task 7: settings window (commands + vanilla-TS UI)

**Files:**
- Create: `apps/tray/src-tauri/src/commands.rs`
- Modify: `apps/tray/src-tauri/src/lib.rs` (add `mod commands;`, register handlers, replace `show_settings_placeholder`)
- Modify: `apps/tray/index.html`, `apps/tray/src/main.ts`, `apps/tray/src/styles.css` (replace template content)

**Interfaces:**
- Consumes: Task 5's `settings::*` and `laris::*` exactly as declared; `AppState` from Task 6.
- Produces: tauri commands `get_settings() -> SettingsPayload`, `save_laris_settings(updates: Map) -> Result<(), String>`, `save_miris_config(vault_root, llm_command: Vec<String>, categories: Vec<(String, String)>) -> Result<(), String>`, `save_theme(updates: Value) -> Result<Value, String>`; `pub fn show_settings_window(app: &AppHandle)`.

- [ ] **Step 1: `commands.rs`**

```rust
//! Tauri commands backing the settings window.

use std::path::PathBuf;
use std::sync::atomic::Ordering;

use tauri::{AppHandle, Manager};

use crate::{laris, settings, AppState};

const KNOWN_LARIS_KEYS: [&str; 4] =
    ["ASSISTANT_MODE", "DICTATE_KEY", "STT_MODEL", "NOISE_REDUCTION"];

#[derive(serde::Serialize)]
pub struct SettingsPayload {
    laris: serde_json::Map<String, serde_json::Value>,
    miris: serde_json::Value,
    theme: Option<serde_json::Value>,
    laris_alive: bool,
    version: String,
}

fn peer() -> Option<laris::LarisPeer> {
    laris::read_peer(&settings::config_dir().join("peers.json"))
}

#[tauri::command]
pub fn get_settings(app: AppHandle) -> SettingsPayload {
    let state = app.state::<AppState>();
    let miris_toml = PathBuf::from(&state.config.miris_home).join("config.toml");
    let peer = peer();
    let laris_alive = peer.as_ref().map(|p| laris::alive(&p.url)).unwrap_or(false);
    let theme = peer
        .filter(|_| laris_alive)
        .and_then(|p| laris::get_theme(&p).ok())
        .and_then(|mut body| body.get_mut("theme").map(serde_json::Value::take));
    SettingsPayload {
        laris: settings::read_json_map(&settings::laris_settings_path()),
        miris: settings::read_miris_config(&miris_toml)
            .unwrap_or_else(|_| serde_json::json!({})),
        theme,
        laris_alive,
        version: app.package_info().version.to_string(),
    }
}

#[tauri::command]
pub fn save_laris_settings(
    app: AppHandle,
    updates: serde_json::Map<String, serde_json::Value>,
) -> Result<(), String> {
    if let Some(bad) = updates.keys().find(|k| !KNOWN_LARIS_KEYS.contains(&k.as_str())) {
        return Err(format!("unknown setting: {bad}"));
    }
    let path = settings::laris_settings_path();
    let mut map = settings::read_json_map(&path);
    for (k, v) in updates {
        map.insert(k, v);
    }
    settings::write_json_atomic(&path, &serde_json::Value::Object(map))?;
    // apply immediately when the tray owns the daemon (settings load at boot)
    let state = app.state::<AppState>();
    let mut daemon = state.daemon.lock().unwrap();
    if daemon.owns_running() {
        daemon.stop();
        daemon.spawn()?;
    }
    Ok(())
}

#[tauri::command]
pub fn save_miris_config(
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
pub fn save_theme(updates: serde_json::Value) -> Result<serde_json::Value, String> {
    let peer = peer().ok_or("laris offline")?;
    laris::set_theme(&peer, updates)
}

pub fn show_settings_window(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("settings") {
        let _ = w.show();
        let _ = w.set_focus();
        return;
    }
    let _ = tauri::WebviewWindowBuilder::new(
        app,
        "settings",
        tauri::WebviewUrl::default(),
    )
    .title("VOXIS - Configurações")
    .inner_size(560.0, 680.0)
    .build();
}
```

In `lib.rs`: add `mod commands;`, delete `show_settings_placeholder` and change the `"settings"` arm to `commands::show_settings_window(app)`, and register the handlers on the builder:

```rust
        .invoke_handler(tauri::generate_handler![
            commands::get_settings,
            commands::save_laris_settings,
            commands::save_miris_config,
            commands::save_theme,
        ])
```

Also make `AppState` fields and modules visible to commands.rs (`pub(crate)` is enough if not already `pub`).

- [ ] **Step 2: `index.html`**

Replace the template's `index.html` body content:

```html
<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>VOXIS - Configurações</title>
    <link rel="stylesheet" href="/src/styles.css" />
    <script type="module" src="/src/main.ts" defer></script>
  </head>
  <body>
    <main>
      <section id="ditado">
        <h2>Ditado</h2>
        <label>Tecla de ativação
          <select id="dictate-key"></select>
        </label>
        <label>Hands-free por padrão
          <input type="checkbox" id="hands-free" />
        </label>
        <label>Modelo STT
          <input type="text" id="stt-model" spellcheck="false" />
        </label>
        <label>Redução de ruído
          <select id="noise">
            <option value="on">Ligada</option>
            <option value="off">Desligada</option>
          </select>
        </label>
        <p class="hint">Salvar reinicia o daemon de ditado se ele estiver ativo.</p>
        <button id="save-laris">Salvar ditado</button>
      </section>

      <section id="reunioes">
        <h2>Reuniões</h2>
        <label>Vault
          <input type="text" id="vault-root" spellcheck="false" />
        </label>
        <label>Comando LLM (um argumento por linha)
          <textarea id="llm-command" rows="4" spellcheck="false"></textarea>
        </label>
        <h3>Categorias</h3>
        <table id="categories">
          <thead><tr><th>Categoria</th><th>Pasta no vault</th><th></th></tr></thead>
          <tbody></tbody>
        </table>
        <button id="add-category" type="button">Adicionar categoria</button>
        <button id="save-miris">Salvar reuniões</button>
      </section>

      <section id="orb">
        <h2>Orb</h2>
        <p class="hint" id="orb-offline" hidden>Ditado desligado - ligue-o para ajustar o orb.</p>
        <label>Arquétipo
          <select id="orb-archetype">
            <option>waveform</option><option>reactor</option><option>faceted</option>
          </select>
        </label>
        <label>Paleta
          <select id="orb-palette">
            <option>blade</option><option>noir</option><option>acid</option><option>ember</option>
          </select>
        </label>
        <label>Posição
          <select id="orb-position">
            <option>center</option><option>top-left</option><option>top-center</option>
            <option>top-right</option><option>bottom-left</option><option>bottom-right</option>
          </select>
        </label>
        <label>Tamanho (80-400)
          <input type="number" id="orb-size" min="80" max="400" step="10" />
        </label>
        <button id="save-orb">Aplicar</button>
      </section>

      <section id="sobre">
        <h2>Sobre</h2>
        <p>VOXIS <span id="version"></span> - ditado (LARIS) e reuniões (MIRIS).</p>
      </section>

      <p id="feedback" role="status"></p>
    </main>
  </body>
</html>
```

- [ ] **Step 3: `src/main.ts`**

```typescript
import { invoke } from "@tauri-apps/api/core";

type Settings = {
  laris: Record<string, string>;
  miris: {
    vault_root?: string;
    llm_command?: string[];
    categories?: Record<string, string>;
  };
  theme: {
    archetype: string;
    palette: string;
    position: string;
    size: number;
  } | null;
  laris_alive: boolean;
  version: string;
};

// mirrors laris/hotkey.py _ALLOWED (ctrl/alt are broken as global hotkeys on macOS)
const DICTATE_KEYS = [
  "cmd_r", "cmd_l", "shift_r", "shift_l",
  "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12", "f13", "f14", "f15",
];

const $ = <T extends HTMLElement>(sel: string) =>
  document.querySelector(sel) as T;

function feedback(msg: string, isError = false) {
  const el = $<HTMLParagraphElement>("#feedback");
  el.textContent = msg;
  el.classList.toggle("error", isError);
  setTimeout(() => { el.textContent = ""; }, 4000);
}

function categoryRow(name = "", folder = ""): HTMLTableRowElement {
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><input type="text" class="cat-name" value=""></td>
    <td><input type="text" class="cat-folder" value=""></td>
    <td><button type="button" class="remove">x</button></td>`;
  (tr.querySelector(".cat-name") as HTMLInputElement).value = name;
  (tr.querySelector(".cat-folder") as HTMLInputElement).value = folder;
  (tr.querySelector(".remove") as HTMLButtonElement).onclick = () => tr.remove();
  return tr;
}

async function load() {
  const s = await invoke<Settings>("get_settings");

  const keySelect = $<HTMLSelectElement>("#dictate-key");
  keySelect.innerHTML = DICTATE_KEYS
    .map((k) => `<option value="${k}">${k}</option>`)
    .join("");
  keySelect.value = s.laris.DICTATE_KEY ?? "cmd_r";
  $<HTMLInputElement>("#hands-free").checked =
    s.laris.ASSISTANT_MODE === "always_on";
  $<HTMLInputElement>("#stt-model").value =
    s.laris.STT_MODEL ?? "mlx-community/whisper-large-v3-turbo-q4";
  $<HTMLSelectElement>("#noise").value = s.laris.NOISE_REDUCTION ?? "on";

  $<HTMLInputElement>("#vault-root").value = s.miris.vault_root ?? "~/vault";
  $<HTMLTextAreaElement>("#llm-command").value =
    (s.miris.llm_command ?? []).join("\n");
  const tbody = $<HTMLTableSectionElement>("#categories tbody");
  tbody.innerHTML = "";
  for (const [name, folder] of Object.entries(s.miris.categories ?? {})) {
    tbody.appendChild(categoryRow(name, folder));
  }

  const orbOffline = !s.laris_alive || s.theme === null;
  $<HTMLParagraphElement>("#orb-offline").hidden = !orbOffline;
  for (const id of ["#orb-archetype", "#orb-palette", "#orb-position", "#orb-size", "#save-orb"]) {
    ($(id) as HTMLInputElement | HTMLSelectElement | HTMLButtonElement).disabled = orbOffline;
  }
  if (s.theme) {
    $<HTMLSelectElement>("#orb-archetype").value = s.theme.archetype;
    $<HTMLSelectElement>("#orb-palette").value = s.theme.palette;
    $<HTMLSelectElement>("#orb-position").value = s.theme.position;
    $<HTMLInputElement>("#orb-size").value = String(s.theme.size);
  }

  $<HTMLSpanElement>("#version").textContent = s.version;
}

function bind() {
  $<HTMLButtonElement>("#add-category").onclick = () =>
    $<HTMLTableSectionElement>("#categories tbody").appendChild(categoryRow());

  $<HTMLButtonElement>("#save-laris").onclick = async () => {
    try {
      await invoke("save_laris_settings", {
        updates: {
          DICTATE_KEY: $<HTMLSelectElement>("#dictate-key").value,
          ASSISTANT_MODE: $<HTMLInputElement>("#hands-free").checked
            ? "always_on"
            : "ptt",
          STT_MODEL: $<HTMLInputElement>("#stt-model").value.trim(),
          NOISE_REDUCTION: $<HTMLSelectElement>("#noise").value,
        },
      });
      feedback("Ditado salvo.");
    } catch (e) {
      feedback(String(e), true);
    }
  };

  $<HTMLButtonElement>("#save-miris").onclick = async () => {
    const categories: [string, string][] = [];
    for (const tr of $<HTMLTableSectionElement>("#categories tbody").rows) {
      const name = (tr.querySelector(".cat-name") as HTMLInputElement).value.trim();
      const folder = (tr.querySelector(".cat-folder") as HTMLInputElement).value.trim();
      if (name && folder) categories.push([name, folder]);
    }
    try {
      await invoke("save_miris_config", {
        vaultRoot: $<HTMLInputElement>("#vault-root").value.trim(),
        llmCommand: $<HTMLTextAreaElement>("#llm-command").value
          .split("\n").map((l) => l.trim()).filter(Boolean),
        categories,
      });
      feedback("Reuniões salvas.");
    } catch (e) {
      feedback(String(e), true);
    }
  };

  $<HTMLButtonElement>("#save-orb").onclick = async () => {
    try {
      await invoke("save_theme", {
        updates: {
          archetype: $<HTMLSelectElement>("#orb-archetype").value,
          palette: $<HTMLSelectElement>("#orb-palette").value,
          position: $<HTMLSelectElement>("#orb-position").value,
          size: Number($<HTMLInputElement>("#orb-size").value),
        },
      });
      feedback("Tema aplicado.");
    } catch (e) {
      feedback(String(e), true);
    }
  };
}

load().then(bind).catch((e) => feedback(String(e), true));
```

- [ ] **Step 4: `src/styles.css`**

System-native sober look (spec style A), light/dark aware:

```css
:root {
  color-scheme: light dark;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 13px;
}
body { margin: 0; }
main { max-width: 520px; margin: 0 auto; padding: 16px 20px 32px; }
section { margin-bottom: 24px; }
h2 { font-size: 15px; border-bottom: 1px solid color-mix(in srgb, currentColor 20%, transparent); padding-bottom: 4px; }
h3 { font-size: 13px; }
label { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin: 8px 0; }
input[type="text"], input[type="number"], select, textarea { flex: 1; max-width: 300px; }
textarea { font-family: ui-monospace, monospace; }
table { width: 100%; border-collapse: collapse; }
table input { width: 95%; }
button { margin-top: 8px; }
.hint { opacity: 0.65; font-size: 12px; }
#feedback { min-height: 1.2em; font-weight: 600; }
#feedback.error { color: #e5484d; }
```

- [ ] **Step 5: Type-check + compile**

```bash
cd ~/code/voxis/apps/tray && npx tsc --noEmit && cd src-tauri && cargo test 2>&1 | tail -5; echo exit=$?
```
Expected: `exit=0`, 17 tests still passing, no TS errors.

- [ ] **Step 6: Manual smoke**

`npm run tauri dev` -> "Configurações..." opens the native window; every section loads current values; save Ditado with a new DICTATE_KEY -> `laris-settings.json` updated and (if daemon on) the boot log prints the new PTT key; save Reuniões -> `~/.miris/config.toml` keeps its comments; Orb section applies live when dictation is on, shows the offline hint when off.

- [ ] **Step 7: Commit**

```bash
cd ~/code/voxis && git add apps/tray && git commit -m "feat(tray): native settings window for laris, miris and orb theme"
```

---

### Task 8: release build, docs, DoD

**Files:**
- Create: `apps/tray/README.md`
- Modify: `README.md` (repo root - add apps/tray to the family table)

**Interfaces:** none - packaging and docs.

- [ ] **Step 1: Release build (host, DoD requirement)**

```bash
cd ~/code/voxis/apps/tray && npm run tauri build 2>&1 | tail -15; echo exit=$?
```
Expected: `exit=0`; artifacts under `src-tauri/target/release/bundle/` (`macos/VOXIS.app`, `dmg/VOXIS_0.1.0_aarch64.dmg`). Signing/notarization intentionally absent (documented, spec out-of-scope).

- [ ] **Step 2: Install-and-run smoke**

Open the .dmg, drag VOXIS.app to /Applications (or run in place), launch: tray icon appears, menu works against live engines. macOS will warn about the unsigned app - right-click > Open once.

- [ ] **Step 3: `apps/tray/README.md`**

```markdown
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
```

- [ ] **Step 4: Root README row**

Add to the family table in `~/code/voxis/README.md`:

```markdown
| apps/tray | VOXIS Tray - system-tray control surface (Tauri v2) | macOS/Win/Linux |
```

- [ ] **Step 5: Full-repo verification**

```bash
cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/ -q > /tmp/claude/laris-final.log 2>&1; echo laris=$?
cd ~/code/voxis/packages/miris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/ -q > /tmp/claude/miris-final.log 2>&1; echo miris=$?
cd ~/code/voxis/apps/tray/src-tauri && cargo test 2>&1 | tail -3; echo tray=$?
```
Expected: `laris=0` (155), `miris=0` (33), `tray=0` (17).

- [ ] **Step 6: Commit + push**

```bash
cd ~/code/voxis && git add apps/tray README.md && \
  git commit -m "docs(tray): README, install notes and repo family table" && git push
```
