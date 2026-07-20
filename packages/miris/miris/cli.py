"""miris - meeting recorder CLI: start | stop | status | retry | doctor."""
import argparse
import datetime as dt
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from miris import config, pipeline


def _pid_alive(pid: int) -> bool:
    """True if `pid` names a running process.

    `os.kill(pid, 0)` is not a portable liveness probe: on Windows a dead pid
    makes it raise a bare `OSError` (WinError 87, ERROR_INVALID_PARAMETER),
    not `ProcessLookupError`, so the usual `except ProcessLookupError` misses
    it and the traceback escapes to the user. Query the process object
    directly there instead.
    """
    if sys.platform == "win32":
        import ctypes

        SYNCHRONIZE = 0x00100000
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        WAIT_TIMEOUT = 0x102
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.OpenProcess(
            SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False  # no such process (or exited and fully reaped)
        try:
            # a process object is signalled once the process exits; still
            # waiting means still running (exact, unlike STILL_ACTIVE==259)
            return k32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        # PermissionError means someone else's process reused the pid: not ours
        return False


def _live_session(cfg: config.Config):
    """Newest session with a live recorder pid, or (None, None). Stale pidfiles
    (process gone) are removed on the way."""
    if not cfg.sessions_dir.exists():
        return None, None
    for session in sorted(cfg.sessions_dir.iterdir(), reverse=True):
        pid_file = session / "recorder.pid"
        if not pid_file.exists():
            continue
        try:
            pid = int(pid_file.read_text())
        except (ValueError, OSError):
            pid_file.unlink(missing_ok=True)  # corrupt or truncated write
            continue
        if not _pid_alive(pid):
            pid_file.unlink(missing_ok=True)  # stale
            continue
        return session, pid
    return None, None


def cmd_start(cfg: config.Config) -> None:
    """Spawn the detached recorder for a fresh session."""
    session, pid = _live_session(cfg)
    if session:
        sys.exit(f"already recording: {session.name} (pid {pid})")
    session = cfg.sessions_dir / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    session.mkdir(parents=True)
    # own stdio for the recorder: inheriting the CLI's pipes would keep them
    # open for the whole recording, deadlocking any caller that reads them
    # (the VOXIS tray collects this CLI's output)
    with (session / "recorder.log").open("ab") as log:
        if getattr(sys, "frozen", False):
            # Frozen executable: use __recorder subcommand with platform-specific detach
            if sys.platform == "win32":
                # Windows: CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS
                subprocess.Popen([sys.executable, "__recorder", str(session)],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                 creationflags=0x00000200 | 0x00000008)
            else:
                # macOS: use start_new_session
                subprocess.Popen([sys.executable, "-m", "miris.recorder", str(session)],
                                 start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log)
        else:
            # Unfrozen (development): use -m miris.recorder with start_new_session
            subprocess.Popen([sys.executable, "-m", "miris.recorder", str(session)],
                             start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=log)
    for _ in range(50):
        if (session / "recorder.pid").exists():
            print(f"recording -> {session}")
            return
        time.sleep(0.1)
    sys.exit("recorder did not start (check mic / system-audio permissions)")


def cmd_stop(cfg: config.Config) -> None:
    """Stop the live recorder and run the post-meeting pipeline."""
    session, pid = _live_session(cfg)
    if not session:
        sys.exit("no active recording")
    pid_file = session / "recorder.pid"
    stop_sentinel = session / "stop"

    # Create stop sentinel for cross-platform shutdown (especially Windows frozen)
    stop_sentinel.touch()

    # Try SIGTERM on Unix, but don't fail if unsupported (Windows frozen)
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, OSError):
        pass

    while pid_file.exists():
        if not _pid_alive(pid):  # died hard without cleanup - don't hang
            pid_file.unlink(missing_ok=True)
            break
        time.sleep(0.2)
    print("recording finished, processing...")
    note = pipeline.process_session(cfg, session)
    print(f"note: {note}")


def cmd_status(cfg: config.Config) -> None:
    session, pid = _live_session(cfg)
    if session:
        mic = session / "mic.wav"
        size = mic.stat().st_size if mic.exists() else 0
        print(f"recording: {session.name} (pid {pid}, mic.wav {size} bytes)")
    else:
        print("idle")


def cmd_retry(cfg: config.Config, session_id: str) -> None:
    """Re-run the pipeline for an existing session (cached transcript reused)."""
    session = cfg.sessions_dir / session_id
    if not session.is_dir():
        sys.exit(f"unknown session: {session_id}")
    note = pipeline.process_session(cfg, session)
    print(f"note: {note}")


def cmd_doctor(cfg: config.Config) -> None:
    """End-to-end smoke: binary, vault, llm, 3s system-audio capture."""
    import tempfile

    from miris.systemtap import SystemTap, default_tap_factory
    ok = True

    # Platform-specific system audio check
    if sys.platform != "win32":
        # macOS/Linux: check audiotap binary
        tap_bin = SystemTap(Path("/dev/null")).binary
        print(f"[{'ok' if tap_bin.exists() else 'FAIL'}] audiotap binary: {tap_bin}")
        ok &= tap_bin.exists()
        tap_check_required = tap_bin.exists()
    else:
        # Windows: check WASAPI loopback availability (no binary to check)
        print("[ok] system audio: WASAPI loopback (Windows)")
        tap_check_required = True

    print(f"[{'ok' if cfg.vault_root.is_dir() else 'FAIL'}] vault_root: {cfg.vault_root}")
    ok &= cfg.vault_root.is_dir()

    print(f"[{'ok' if cfg.categories else 'WARN'}] categories configured: "
          f"{list(cfg.categories) or 'none (everything goes to inbox)'}")

    # Resolve llm_command[0] via shutil.which to handle .cmd/.exe shims on Windows
    llm_cmd = list(cfg.llm_command)
    resolved_bin = shutil.which(llm_cmd[0])
    if resolved_bin:
        llm_cmd[0] = resolved_bin
    try:
        llm = subprocess.run(llm_cmd + ["Responda apenas: OK"],
                             capture_output=True, text=True, timeout=120)
        llm_ok = llm.returncode == 0 and llm.stdout.strip() != ""
    except (OSError, subprocess.TimeoutExpired):
        llm_ok = False
    print(f"[{'ok' if llm_ok else 'FAIL'}] llm_command: {' '.join(cfg.llm_command)}")
    ok &= llm_ok

    if tap_check_required:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "tap-smoke.wav"
            tap_factory_func = default_tap_factory()
            tap = tap_factory_func(out)
            try:
                tap.start()
                time.sleep(3)
            finally:
                tap.stop()  # never leave an orphan capture process
            tap_worked = out.exists() and out.stat().st_size > 44
            print(f"[{'ok' if tap_worked else 'FAIL'}] system-audio smoke "
                  f"(3s): {out.stat().st_size if out.exists() else 0} bytes")
            ok &= tap_worked

    sys.exit(0 if ok else 1)


def main() -> None:
    # private meeting audio/transcripts/notes must not be world-readable;
    # inherited by the detached recorder subprocess too
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog="miris")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("status")
    retry = sub.add_parser("retry")
    retry.add_argument("session_id")
    sub.add_parser("doctor")
    args = parser.parse_args()

    cfg = config.load()
    if args.command == "start":
        cmd_start(cfg)
    elif args.command == "stop":
        cmd_stop(cfg)
    elif args.command == "status":
        cmd_status(cfg)
    elif args.command == "retry":
        cmd_retry(cfg, args.session_id)
    elif args.command == "doctor":
        cmd_doctor(cfg)


if __name__ == "__main__":
    main()
