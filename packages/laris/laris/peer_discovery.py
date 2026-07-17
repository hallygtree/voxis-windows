"""Inter-daemon peer discovery via ~/.config/voice-at/peers.json.

Three daemons (panel, laris, kiris) live in separate OS processes in the
three-process split. Each writes its own entry (url + optional token) on
boot via write_peer(); reads the others via peer_url()/peer_token(). The
file is small (6 lines), best-effort, and never blocks a daemon's boot
if absent or malformed.

Vendored byte-identically into all three repos (claude-code-ops/backend,
laris/laris, kiris/kiris). Keep copies in sync."""
from __future__ import annotations

import json
import os
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

_peers_path_override: Path | None = None  # test hook


def peers_path() -> Path:
    override = globals().get("_peers_path_override")
    if override is not None:
        return override
    return Path.home() / ".config" / "voice-at" / "peers.json"


def read_peers() -> dict[str, dict]:
    """Returns {} if the file is missing or unparseable. Never raises."""
    path = peers_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def write_peer(name: str, url: str, token: str | None = None) -> None:
    """Atomically update peers[name]. Creates the parent dir if missing."""
    path = peers_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = read_peers()
    data[name] = {"url": url}
    if token is not None:
        data[name]["token"] = token
    # 0600: this file holds the bearer token - mkstemp creates it 0600 so a
    # second local account can't read the token off a multi-user machine
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2))
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def peer_url(name: str) -> str | None:
    return read_peers().get(name, {}).get("url")


def peer_token(name: str) -> str | None:
    return read_peers().get(name, {}).get("token")


def peer_offline(name: str, http_get: Callable = urllib.request.urlopen) -> bool:
    """True if the peer is offline (no entry, connect fails, or non-2xx)."""
    url = peer_url(name)
    if url is None:
        return True
    try:
        with http_get(url, timeout=0.5) as resp:
            return not (200 <= resp.status < 300)
    except Exception:  # noqa: BLE001
        return True
