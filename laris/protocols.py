"""Structural types LARIS needs from whatever session/session-list source
it's handed - keeps LARIS's voice modules free of a PANEL import
(lr.SessionInfo). Any object with these fields works; no
inheritance required (see rules/python/patterns.md's Protocol example)."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol


class SessionLike(Protocol):
    name: str
    project: str
    tmux_name: str
    last_active: datetime | None


class AssistantProtocol(Protocol):
    def handle(self, request: str) -> None: ...
    def handle_followup(self, text: str) -> bool: ...
