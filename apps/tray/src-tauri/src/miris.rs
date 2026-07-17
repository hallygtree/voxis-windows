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
        // pid <= 0 means "own process group" / "everyone" to kill(2) - a
        // corrupt pidfile would read as permanently alive without this guard
        if pid > 0 && pid_alive(pid) {
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
        let tail: Vec<&str> = tail.into_iter().rev().collect();
        // exit status prefix so an empty stderr still yields a usable error
        Err(format!("miris {arg} exited {}: {}", out.status, tail.join("\n")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;
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
    fn status_treats_non_positive_pids_as_dead() {
        let tmp = tempfile::tempdir().unwrap();
        session(tmp.path(), "20260716-130000", Some(0));
        session(tmp.path(), "20260716-140000", Some(-1));
        assert_eq!(status(tmp.path()), MirisStatus::Idle);
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
