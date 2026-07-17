import json
from pathlib import Path

import pytest

from laris import peer_discovery


@pytest.fixture
def isolated_peers_path(tmp_path, monkeypatch):
    peers = tmp_path / "voice-at" / "peers.json"
    monkeypatch.setattr(peer_discovery, "_peers_path_override", peers)
    return peers


def test_peers_path_default(monkeypatch):
    monkeypatch.delattr(peer_discovery, "_peers_path_override", raising=False)
    expected = Path.home() / ".config" / "voice-at" / "peers.json"
    assert peer_discovery.peers_path() == expected


def test_read_peers_returns_empty_when_missing(isolated_peers_path):
    assert peer_discovery.read_peers() == {}


def test_read_peers_returns_dict_when_well_formed(isolated_peers_path):
    isolated_peers_path.parent.mkdir(parents=True, exist_ok=True)
    isolated_peers_path.write_text('{"panel": {"url": "http://x", "token": "t"}}')
    assert peer_discovery.read_peers() == {
        "panel": {"url": "http://x", "token": "t"}
    }


def test_read_peers_returns_empty_on_malformed_json(isolated_peers_path):
    isolated_peers_path.parent.mkdir(parents=True, exist_ok=True)
    isolated_peers_path.write_text("{not json")
    # MUST NOT raise - daemon boot is best-effort
    assert peer_discovery.read_peers() == {}


def test_write_peer_creates_file_and_dir(isolated_peers_path):
    peer_discovery.write_peer("laris", "http://127.0.0.1:8421", token="abc")
    assert isolated_peers_path.exists()
    data = json.loads(isolated_peers_path.read_text())
    assert data == {"laris": {"url": "http://127.0.0.1:8421", "token": "abc"}}


def test_write_peer_preserves_other_entries(isolated_peers_path):
    peer_discovery.write_peer("panel", "http://127.0.0.1:8420")
    peer_discovery.write_peer("laris", "http://127.0.0.1:8421", token="abc")
    data = json.loads(isolated_peers_path.read_text())
    assert set(data.keys()) == {"panel", "laris"}
    assert data["panel"] == {"url": "http://127.0.0.1:8420"}
    assert data["laris"] == {"url": "http://127.0.0.1:8421", "token": "abc"}


def test_write_peer_omits_token_when_none(isolated_peers_path):
    peer_discovery.write_peer("panel", "http://127.0.0.1:8420")
    data = json.loads(isolated_peers_path.read_text())
    assert "token" not in data["panel"]


def test_write_peer_overrides_same_name(isolated_peers_path):
    peer_discovery.write_peer("panel", "http://a")
    peer_discovery.write_peer("panel", "http://b", token="x")
    data = json.loads(isolated_peers_path.read_text())
    assert data == {"panel": {"url": "http://b", "token": "x"}}


def test_peer_url_returns_none_when_missing(isolated_peers_path):
    assert peer_discovery.peer_url("panel") is None


def test_peer_url_returns_url_when_present(isolated_peers_path):
    peer_discovery.write_peer("panel", "http://127.0.0.1:8420")
    assert peer_discovery.peer_url("panel") == "http://127.0.0.1:8420"


def test_peer_token_returns_none_when_omitted(isolated_peers_path):
    peer_discovery.write_peer("panel", "http://x")
    assert peer_discovery.peer_token("panel") is None


def test_peer_token_returns_string_when_present(isolated_peers_path):
    peer_discovery.write_peer("laris", "http://x", token="tok")
    assert peer_discovery.peer_token("laris") == "tok"


def test_peer_offline_returns_true_when_missing(isolated_peers_path):
    assert peer_discovery.peer_offline("panel") is True


def test_peer_offline_returns_true_when_get_fails(isolated_peers_path):
    peer_discovery.write_peer("panel", "http://127.0.0.1:8420")
    def boom(url, timeout=None):
        raise OSError("refused")
    assert peer_discovery.peer_offline("panel", http_get=boom) is True


def test_peer_offline_returns_false_when_get_succeeds(isolated_peers_path):
    peer_discovery.write_peer("panel", "http://127.0.0.1:8420")
    class FakeResp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b"ok"
    def ok(url, timeout=None): return FakeResp()
    assert peer_discovery.peer_offline("panel", http_get=ok) is False


def test_peer_offline_returns_true_on_non_2xx(isolated_peers_path):
    peer_discovery.write_peer("panel", "http://127.0.0.1:8420")
    class FakeResp:
        status = 500
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b"oops"
    def fail(url, timeout=None): return FakeResp()
    assert peer_discovery.peer_offline("panel", http_get=fail) is True
