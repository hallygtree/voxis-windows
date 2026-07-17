from laris import orb_theme
from laris.overlay_app import panel_rect_for_theme


def test_panel_rect_uses_theme_position_and_size():
    theme = dict(orb_theme.DEFAULTS, position="bottom-right", size=100)
    x, y, w, h = panel_rect_for_theme(theme, 1000.0, 800.0)
    assert (x, y, w, h) == (1000 - 100 - 16.0, 16.0, 100.0, 100.0)
