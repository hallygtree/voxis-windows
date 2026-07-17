"""LARIS's HTTP client wrappers for the panel and Kiris daemons.

In the three-process split, VoiceSession's injected callables are either
HTTP-backed (when the peer is online per peers.json) or no-op stubs (when
offline). Standalone LARIS with no panel = pure dictation; standalone LARIS
with panel but no Kiris = dictation + project commands; with Kiris = full
assistant dispatch."""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any

from laris.protocols import SessionLike


@dataclass(frozen=True)
class PanelSession:
    """Adapted shape of the panel's GET /api/sessions response. Satisfies
    SessionLike structurally (has name, project, tmux_name, last_active)."""
    name: str
    project: str
    tmux_name: str
    last_active: Any  # isoformat-string OR null - session_machine only reads .name/.project/.tmux_name/.last_active
    cwd: str
    state: str
    tmux_pid: int
    git_branch: str | None


class PanelClient:
    def __init__(self, panel_url: str | None, panel_token: str | None) -> None:
        self.panel_url = panel_url.rstrip("/") if panel_url else None
        self.panel_token = panel_token

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        if self.panel_url is None:
            return None
        url = f"{self.panel_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        if self.panel_token:
            req.add_header("X-Session-Token", self.panel_token)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return json.loads(resp.read())

    def get_sessions(self) -> list[SessionLike]:
        if self.panel_url is None:
            return []
        try:
            raw = self._request("GET", "/api/sessions") or []
            return [
                PanelSession(
                    name=s["name"],
                    project=s.get("project", s["name"]),
                    tmux_name=s["tmux_name"],
                    last_active=s.get("last_active"),
                    cwd=s["cwd"],
                    state=s.get("state", "WORKING"),
                    tmux_pid=s.get("tmux_pid", 0),
                    git_branch=s.get("git_branch"),
                )
                for s in raw
            ]
        except Exception:  # noqa: BLE001 - panel offline -> empty session list
            return []

    def send_text(self, session: str, text: str) -> None:
        if self.panel_url is None:
            return
        try:
            self._request("POST", f"/api/sessions/{session}/send-text", {"text": text})
        except Exception:  # noqa: BLE001
            raise

    def send_enter(self, session: str) -> None:
        if self.panel_url is None:
            return
        try:
            self._request("POST", f"/api/sessions/{session}/send-enter")
        except Exception:  # noqa: BLE001
            raise

    def spawn_and_target(self, project: str) -> SessionLike | None:
        if self.panel_url is None:
            return None
        from pathlib import Path
        for root in (Path.home() / "code", Path.home() / "dev"):
            cwd = root / project
            if cwd.is_dir():
                try:
                    self._request("POST", "/api/sessions/spawn", {"name": project, "cwd": str(cwd)})
                except Exception:  # noqa: BLE001
                    return None
                # Wait briefly for tmux to register, then re-query sessions
                import time
                for _ in range(3):
                    time.sleep(1.0)
                    for s in self.get_sessions():
                        if s.cwd == str(cwd):
                            return s
                return None
        return None

    def end_session(self, session: str) -> None:
        if self.panel_url is None:
            return
        try:
            self._request("POST", f"/api/sessions/{session}/end")
        except Exception:  # noqa: BLE001
            raise


class KirisClient:
    """LARIS POSTs spoken feedback strings AND 'kiris <pedido>' matches here.
    For spoken feedback (on_feedback), KIRIS calls kiris.tts.speak locally;
    for assistant dispatch (ask), KIRIS runs the LLM and the actions."""

    def __init__(self, kiris_url: str | None) -> None:
        self.kiris_url = kiris_url.rstrip("/") if kiris_url else None

    def ask(self, request: str) -> bool:
        """POST /ask to kiris. Returns True on 2xx, False on offline/error
        (route_utterance treats False as 'kiris offline -> dictation fallback')."""
        if self.kiris_url is None:
            return False
        try:
            url = f"{self.kiris_url}/ask"
            data = json.dumps({"request": request}).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=30) as resp:
                return 200 <= resp.status < 300
        except Exception:  # noqa: BLE001
            return False

    def speak(self, text: str) -> None:
        """Send a speak-only request to kiris (no LLM run). Reuses /ask with
        the text - if offline, swallows silently (LARIS is mute by design)."""
        self.ask(text)
