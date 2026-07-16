import os

from miris.config import Config
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


def test_live_session_cleans_stale_pid(tmp_path):
    cfg = _cfg(tmp_path)
    session = cfg.sessions_dir / "20260716-1000"
    session.mkdir(parents=True)
    (session / "recorder.pid").write_text("999999999")
    assert cli._live_session(cfg) == (None, None)
    assert not (session / "recorder.pid").exists()
