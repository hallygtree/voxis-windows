import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from miris.config import Config, STOP_SENTINEL
from miris import cli


def _cfg(tmp_path) -> Config:
    return Config(vault_root=tmp_path / "vault", inbox="inbox", llm_command=["true"],
                  categories={}, sessions_dir=tmp_path / "sessions")


def test_live_session_none_when_empty(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.sessions_dir.mkdir(parents=True)
    assert cli._live_session(cfg) == (None, None)


def test_live_session_finds_running_pid(tmp_path):
    cfg = _cfg(tmp_path)
    session = cfg.sessions_dir / "20260716-1000"
    session.mkdir(parents=True)
    (session / "recorder.pid").write_text(str(os.getpid()))
    assert cli._live_session(cfg) == (session, os.getpid())


def test_live_session_cleans_corrupt_pid(tmp_path):
    cfg = _cfg(tmp_path)
    session = cfg.sessions_dir / "20260716-1000"
    session.mkdir(parents=True)
    (session / "recorder.pid").write_text("")  # truncated write
    assert cli._live_session(cfg) == (None, None)
    assert not (session / "recorder.pid").exists()


def test_cmd_start_detaches_recorder_stdio(tmp_path, monkeypatch):
    """The recorder must not inherit the CLI's stdio: a caller that reads the
    CLI's pipes (the VOXIS tray uses Command::output) would block until the
    recorder exits - i.e. for the entire recording."""
    cfg = _cfg(tmp_path)
    seen = {}

    def fake_popen(args, **kwargs):
        seen.update(kwargs)
        (Path(args[-1]) / "recorder.pid").write_text("12345")

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    cli.cmd_start(cfg)
    assert seen.get("stdin") is subprocess.DEVNULL
    assert seen.get("stdout") is not None
    assert seen.get("stderr") is not None


def test_live_session_cleans_stale_pid(tmp_path):
    cfg = _cfg(tmp_path)
    session = cfg.sessions_dir / "20260716-1000"
    session.mkdir(parents=True)
    (session / "recorder.pid").write_text("999999999")
    assert cli._live_session(cfg) == (None, None)
    assert not (session / "recorder.pid").exists()


def test_cmd_start_reports_what_the_recorder_logged_when_it_dies(tmp_path, monkeypatch):
    """Armadilha nº1: the recorder is detached and the frozen build is
    windowed, so its traceback exists only in recorder.log. Blaming microphone
    permissions while an ImportError sits unread in that file is the failure
    mode this project keeps paying for."""
    cfg = _cfg(tmp_path)

    def fake_popen(args, **kwargs):
        Path(args[-1]).joinpath("recorder.log").write_text(
            "Traceback (most recent call last):\n"
            "ModuleNotFoundError: No module named 'soundcard'\n",
            encoding="utf-8")

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)  # don't wait 5s

    with pytest.raises(SystemExit) as excinfo:
        cli.cmd_start(cfg)
    message = str(excinfo.value)
    assert "ModuleNotFoundError" in message
    assert "recorder.log" in message


def test_cmd_start_says_so_when_the_log_is_empty(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda args, **kw: None)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)

    with pytest.raises(SystemExit) as excinfo:
        cli.cmd_start(cfg)
    assert "logged nothing" in str(excinfo.value)


def _live_session_dir(cfg, pid="4242"):
    session = cfg.sessions_dir / "20260716-1000"
    session.mkdir(parents=True)
    (session / "recorder.pid").write_text(pid)
    return session


def test_cmd_stop_shuts_the_recorder_down_through_the_sentinel(tmp_path, monkeypatch):
    """B2: `miris stop` must ask the recorder to stop by dropping the sentinel
    and then wait for it to clean up, rather than killing it. On Windows
    os.kill is TerminateProcess: killing here truncates mic.wav/system.wav."""
    cfg = _cfg(tmp_path)
    session = _live_session_dir(cfg)
    pid_file = session / "recorder.pid"

    monkeypatch.setattr(cli, "_pid_alive", lambda pid: pid_file.exists())
    signals = []
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: signals.append(sig))
    monkeypatch.setattr(cli.pipeline, "process_session",
                        lambda c, s: s / "note.md")

    def fake_recorder():  # stands in for the detached recorder process
        for _ in range(200):
            if (session / STOP_SENTINEL).exists():
                pid_file.unlink(missing_ok=True)  # its `finally` ran
                return
            time.sleep(0.01)

    worker = threading.Thread(target=fake_recorder)
    worker.start()
    try:
        cli.cmd_stop(cfg)
    finally:
        worker.join(timeout=5)

    assert (session / STOP_SENTINEL).exists(), "sentinel is the stop channel"
    assert not pid_file.exists(), "must wait for the recorder to clean up"
    if sys.platform == "win32":
        assert signals == [], "os.kill on Windows is TerminateProcess"


def test_cmd_stop_force_kills_a_wedged_recorder(tmp_path, monkeypatch):
    """A recorder that ignores the sentinel must not hang the caller forever -
    the tray runs `miris stop` synchronously."""
    cfg = _cfg(tmp_path)
    session = _live_session_dir(cfg)

    monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)  # never dies
    monkeypatch.setattr(cli, "STOP_GRACE_S", 0.3)
    killed = []
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: killed.append(pid))
    monkeypatch.setattr(cli.pipeline, "process_session",
                        lambda c, s: s / "note.md")

    started = time.monotonic()
    cli.cmd_stop(cfg)
    assert time.monotonic() - started < 5, "must give up instead of blocking"
    assert killed == [4242]
    assert not (session / "recorder.pid").exists()
