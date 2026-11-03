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


def test_position_rect_topleft_all_presets():
    theme = dict(orb_theme.DEFAULTS, size=100)
    screen_w, screen_h = 1000.0, 800.0
    # bottom-left is (16, 16) in AppKit coords; converts to (16, 800 - 16 - 100) = (16, 684)
    # top-left is (16, 800 - 100 - 40) in AppKit coords; converts to (16, 40) in Win32 coords
    # For all positions, y_topleft + y_bottomleft + size == screen_h
    cases = {
        "top-left": (16.0, 40.0, 100.0, 100.0),
        "top-center": (450.0, 40.0, 100.0, 100.0),
        "top-right": (884.0, 40.0, 100.0, 100.0),
        "bottom-left": (16.0, 684.0, 100.0, 100.0),
        "bottom-right": (884.0, 684.0, 100.0, 100.0),
        "center": (450.0, 350.0, 100.0, 100.0),
    }
    for preset, (x, y, w, h) in cases.items():
        theme["position"] = preset
        result = orb_theme.position_rect_topleft(theme, screen_w, screen_h)
        assert result == (x, y, w, h), f"Failed for {preset}: got {result}, expected {(x, y, w, h)}"
        # Verify the invariant: y_topleft + y_bottomleft + size == screen_h
        x_bottom, y_bottom = orb_theme.position_rect(theme, screen_w, screen_h)
        size = float(theme["size"])
        assert y + y_bottom + size == screen_h, f"Invariant failed for {preset}"


def test_position_rect_topleft_default_1920x1080():
    theme = dict(orb_theme.DEFAULTS)
    x, y, w, h = orb_theme.position_rect_topleft(theme, 1920.0, 1080.0)
    assert w == 190.0  # size from DEFAULTS
    assert h == 190.0  # size from DEFAULTS
    assert (x, y) == (865.0, 445.0)  # Verified from SDD-C0 example


def test_position_rect_topleft_custom_coordinates():
    theme = dict(orb_theme.DEFAULTS, position="custom", custom=[100, 200], size=100)
    screen_h = 600.0
    x, y, w, h = orb_theme.position_rect_topleft(theme, 1000.0, screen_h)
    assert (x, w, h) == (100.0, 100.0, 100.0)
    # custom[1]=200 in bottom-left becomes y_topleft = 600 - 200 - 100 = 300
    assert y == 300.0
