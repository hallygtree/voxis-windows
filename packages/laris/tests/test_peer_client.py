import json
from unittest.mock import MagicMock, patch

from laris.peer_client import KirisClient, PanelClient


def test_kiris_client_ask_returns_true_on_200():
    fake_resp = MagicMock(status=200)
    fake_resp.__enter__ = lambda self: self
    fake_resp.__exit__ = lambda *a: None
    fake_resp.read.return_value = b'{"ok": true}'
    with patch("urllib.request.urlopen", return_value=fake_resp):
        client = KirisClient(kiris_url="http://127.0.0.1:8422")
        result = client.ask("abre o axon")
    assert result is True


def test_kiris_client_ask_returns_false_when_url_is_none():
    client = KirisClient(kiris_url=None)
    assert client.ask("abre o axon") is False


def test_kiris_client_ask_returns_false_on_exception():
    def boom(url, timeout=None):
        raise OSError("refused")
    with patch("urllib.request.urlopen", side_effect=boom):
        client = KirisClient(kiris_url="http://x")
        result = client.ask("abre o axon")
    assert result is False


def test_panel_client_get_sessions_returns_empty_when_url_none():
    client = PanelClient(panel_url=None, panel_token=None)
    assert client.get_sessions() == []


def test_panel_client_send_text_when_url_none_is_noop():
    client = PanelClient(panel_url=None, panel_token=None)
    client.send_text("lina", "hi")  # no-op, no exception


def test_panel_client_end_session_when_url_none_is_noop():
    client = PanelClient(panel_url=None, panel_token=None)
    client.end_session("lina")  # no-op, no exception


def test_panel_client_spawn_returns_none_when_url_none():
    client = PanelClient(panel_url=None, panel_token=None)
    assert client.spawn_and_target("axon") is None
