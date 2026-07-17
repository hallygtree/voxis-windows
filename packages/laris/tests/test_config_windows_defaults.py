"""On Windows the torch-based denoiser is not bundled, so NOISE_REDUCTION must
default off there (it would otherwise warn once per utterance). macOS keeps it
on. The env override still wins on both."""
import importlib
import sys


def _reload_config_as(platform_name, monkeypatch, env=None):
    monkeypatch.setattr(sys, "platform", platform_name)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    import laris.config as cfg
    return importlib.reload(cfg)


def test_noise_reduction_defaults_off_on_windows(monkeypatch):
    cfg = _reload_config_as("win32", monkeypatch)
    assert cfg.NOISE_REDUCTION == "off"


def test_noise_reduction_defaults_on_elsewhere(monkeypatch):
    cfg = _reload_config_as("darwin", monkeypatch)
    assert cfg.NOISE_REDUCTION == "on"


def test_noise_reduction_env_override_wins_on_windows(monkeypatch):
    cfg = _reload_config_as("win32", monkeypatch, {"NOISE_REDUCTION": "on"})
    assert cfg.NOISE_REDUCTION == "on"


def teardown_module(module):
    # leave the real platform config loaded for the rest of the suite
    import importlib
    import laris.config
    importlib.reload(laris.config)
