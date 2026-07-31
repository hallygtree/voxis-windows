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
    monkeypatch.setenv("STT_MODEL_GGML", "outro.bin")
    cfg = fresh_config()
    assert cfg.DICTATE_KEY == "f13"            # file wins over env
    assert cfg.STT_MODEL_GGML == "outro.bin"   # env wins over default
    assert cfg.MODE == "ptt"               # default when neither set
