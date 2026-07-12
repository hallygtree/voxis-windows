"""LARIS's own token-based auth for its standalone overlay server -
deliberately a separate token from the panel's (backend/auth.py): LARIS must
not import a PANEL module. Same constant-time-compare pattern."""
from __future__ import annotations

import secrets


def generate_token() -> str:
    return secrets.token_hex(16)


def token_valid(token: str | None, current: str | None) -> bool:
    if current is None or token is None:
        return False
    return secrets.compare_digest(current, token)
