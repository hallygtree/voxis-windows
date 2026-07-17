import textwrap
from pathlib import Path

import pytest

from miris import config


def test_load_creates_default_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRIS_HOME", str(tmp_path))
    cfg = config.load()
    assert (tmp_path / "config.toml").exists()
    assert cfg.vault_root == Path("~/vault").expanduser()
    assert cfg.inbox == "inbox"
    assert cfg.llm_command[0] == "agy"
    assert cfg.sessions_dir == tmp_path / "sessions"


def test_load_explicit_missing_path_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRIS_HOME", str(tmp_path))
    missing = tmp_path / "custom" / "nope.toml"
    with pytest.raises(FileNotFoundError):
        config.load(missing)
    assert not missing.parent.exists()  # no silent directory creation


def test_load_parses_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRIS_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text(textwrap.dedent("""\
        vault_root = "/tmp/vault"
        inbox = "caixa"
        llm_command = ["claude", "-p"]
        [categories]
        entrevistas = "interviews"
    """))
    cfg = config.load()
    assert cfg.vault_root == Path("/tmp/vault")
    assert cfg.inbox == "caixa"
    assert cfg.llm_command == ["claude", "-p"]
    assert cfg.categories == {"entrevistas": "interviews"}
