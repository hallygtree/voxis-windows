"""Orb theme config: archetype x palette x position, persisted as JSON.
Single source of truth for the /theme endpoint, overlay_app and the menu bar."""
import json
from pathlib import Path

from laris import config

ARCHETYPES = ("waveform", "reactor", "faceted")
PALETTES = {
    "blade": {"accent": "#3fb6c4", "hot": "#d8f4f7"},
    "noir": {"accent": "#c94f92", "hot": "#f7d8ea"},
    "acid": {"accent": "#79c94f", "hot": "#e9f7d8"},
    "ember": {"accent": "#cf9b3a", "hot": "#f7ecd8"},
}
POSITIONS = ("top-left", "top-center", "top-right",
             "bottom-left", "bottom-right", "center", "custom")
SIZE_RANGE = (80, 400)
_TOP_MARGIN = 40.0
_EDGE_MARGIN = 16.0

DEFAULTS = {
    "archetype": "waveform",
    "palette": "blade",
    "position": "center",
    "custom": [0, 0],
    "size": 190,
}


class ThemeValidationError(ValueError):
    pass


def _theme_path(path: Path | None) -> Path:
    return path or Path(config.ORB_THEME_PATH).expanduser()


def _validate(theme: dict) -> None:
    if theme["archetype"] not in ARCHETYPES:
        raise ThemeValidationError(f"archetype must be one of {ARCHETYPES}")
    if theme["palette"] not in PALETTES:
        raise ThemeValidationError(f"palette must be one of {tuple(PALETTES)}")
    if theme["position"] not in POSITIONS:
        raise ThemeValidationError(f"position must be one of {POSITIONS}")
    size = theme["size"]
    if (isinstance(size, bool) or not isinstance(size, int)
            or not SIZE_RANGE[0] <= size <= SIZE_RANGE[1]):
        raise ThemeValidationError(f"size must be an int in {SIZE_RANGE}")
    custom = theme["custom"]
    if (not isinstance(custom, list) or len(custom) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                       for v in custom)):
        raise ThemeValidationError("custom must be [x, y]")


def load_theme(path: Path | None = None) -> dict:
    """Read the theme; missing or corrupt file resets to DEFAULTS on disk."""
    path = _theme_path(path)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("theme file is not a JSON object")
        theme = {key: {**DEFAULTS, **loaded}[key] for key in DEFAULTS}
        _validate(theme)
        return theme
    except (OSError, ValueError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")
        return dict(DEFAULTS)


def save_theme(updates: dict, path: Path | None = None) -> dict:
    """Merge updates over the stored theme, validate, persist, return it."""
    path = _theme_path(path)
    unknown = set(updates) - set(DEFAULTS)
    if unknown:
        raise ThemeValidationError(
            f"unknown keys: {sorted(unknown)}; valid: {sorted(DEFAULTS)}")
    theme = {**load_theme(path), **updates}
    _validate(theme)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(theme, indent=2), encoding="utf-8")
    return theme


def position_rect(theme: dict, screen_w: float, screen_h: float) -> tuple[float, float]:
    """Bottom-left origin (macOS AppKit convention) for the panel corner."""
    size = float(theme["size"])
    pos = theme["position"]
    if pos == "custom":
        return float(theme["custom"][0]), float(theme["custom"][1])
    x = {
        "left": _EDGE_MARGIN,
        "center": (screen_w - size) / 2,
        "right": screen_w - size - _EDGE_MARGIN,
    }["left" if pos.endswith("left") else "right" if pos.endswith("right") else "center"]
    if pos.startswith("top"):
        y = screen_h - size - _TOP_MARGIN
    elif pos.startswith("bottom"):
        y = _EDGE_MARGIN
    else:  # center
        y = (screen_h - size) / 2
    return x, y
