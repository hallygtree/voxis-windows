import json
from pathlib import Path

import pytest

from laris import orb_theme


def test_load_missing_file_writes_defaults(tmp_path):
    path = tmp_path / "orb-theme.json"
    theme = orb_theme.load_theme(path)
    assert theme == orb_theme.DEFAULTS
    assert json.loads(path.read_text()) == orb_theme.DEFAULTS


def test_load_corrupt_file_rewrites_defaults(tmp_path):
    path = tmp_path / "orb-theme.json"
    path.write_text("{not json")
    assert orb_theme.load_theme(path) == orb_theme.DEFAULTS


@pytest.mark.parametrize("content", ["42", "null", '"foo"', "[1, 2]"])
def test_load_valid_json_but_not_object_resets_defaults(content, tmp_path):
    path = tmp_path / "orb-theme.json"
    path.write_text(content)
    assert orb_theme.load_theme(path) == orb_theme.DEFAULTS
    assert json.loads(path.read_text()) == orb_theme.DEFAULTS


def test_load_drops_unknown_keys(tmp_path):
    path = tmp_path / "orb-theme.json"
    path.write_text(json.dumps({**orb_theme.DEFAULTS, "sneaky": 1}))
    assert "sneaky" not in orb_theme.load_theme(path)


def test_save_rejects_unknown_keys(tmp_path):
    with pytest.raises(orb_theme.ThemeValidationError):
        orb_theme.save_theme({"palete": "blade"}, tmp_path / "orb-theme.json")


def test_save_rejects_bool_size(tmp_path):
    with pytest.raises(orb_theme.ThemeValidationError):
        orb_theme.save_theme({"size": True}, tmp_path / "orb-theme.json")


def test_save_merges_and_persists(tmp_path):
    path = tmp_path / "orb-theme.json"
    theme = orb_theme.save_theme({"palette": "ember"}, path)
    assert theme["palette"] == "ember"
    assert theme["archetype"] == "waveform"  # untouched defaults survive
    assert json.loads(path.read_text())["palette"] == "ember"


@pytest.mark.parametrize("bad", [
    {"archetype": "sphere"},
    {"palette": "rainbow"},
    {"position": "left"},
    {"size": "big"},
    {"size": 20},
    {"custom": [1]},
])
def test_save_rejects_invalid(bad, tmp_path):
    with pytest.raises(orb_theme.ThemeValidationError):
        orb_theme.save_theme(bad, tmp_path / "orb-theme.json")


def test_position_rect_all_presets():
    theme = dict(orb_theme.DEFAULTS, size=100)
    w, h = 1000.0, 800.0
    cases = {
        "top-left": (16.0, 800 - 100 - 40.0),
        "top-center": (450.0, 800 - 100 - 40.0),
        "top-right": (1000 - 100 - 16.0, 800 - 100 - 40.0),
        "bottom-left": (16.0, 16.0),
        "bottom-right": (1000 - 100 - 16.0, 16.0),
        "center": (450.0, 350.0),
    }
    for preset, expected in cases.items():
        theme["position"] = preset
        assert orb_theme.position_rect(theme, w, h) == expected


def test_position_rect_custom_coordinates():
    theme = dict(orb_theme.DEFAULTS, position="custom", custom=[123, 456])
    assert orb_theme.position_rect(theme, 2000.0, 1200.0) == (123.0, 456.0)
