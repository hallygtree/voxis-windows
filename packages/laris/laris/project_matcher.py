"""Fuzzy-matches a spoken project name against known tmux sessions,
handling numbered disambiguation (e.g. "lina dois" -> lina-2)."""
from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from laris.protocols import SessionLike

_NUMBER_WORDS = {
    "um": 1, "uma": 1, "1": 1,
    "dois": 2, "duas": 2, "2": 2,
    "tres": 3, "3": 3,
    "quatro": 4, "4": 4,
    "cinco": 5, "5": 5,
}

_MATCH_CUTOFF = 0.6


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"[.,!?;:]+", "", text)


def _extract_number(normalized: str) -> tuple[str, int | None]:
    """Strip a trailing number word/digit and return (remaining_text, number)."""
    words = normalized.split()
    if words and words[-1] in _NUMBER_WORDS:
        return " ".join(words[:-1]).strip(), _NUMBER_WORDS[words[-1]]
    return normalized, None


def match_project(spoken_text: str, sessions: list[SessionLike]) -> SessionLike | None:
    """Return the best-matching session for a spoken project name, or None.

    Disambiguation when multiple tmux sessions share a project name (e.g.
    "lina" and "lina-2"): an explicit spoken number picks that exact one;
    otherwise the most recently active session wins.
    """
    if not sessions:
        return None

    normalized, number = _extract_number(_normalize(spoken_text))
    projects = {s.project for s in sessions}
    close = difflib.get_close_matches(normalized, projects, n=1, cutoff=_MATCH_CUTOFF)
    if not close:
        return None

    matched_project = close[0]
    candidates = [s for s in sessions if s.project == matched_project]
    if len(candidates) == 1:
        return candidates[0]

    if number is not None:
        target_name = matched_project if number == 1 else f"{matched_project}-{number}"
        for session in candidates:
            if session.name == target_name:
                return session

    return max(candidates, key=lambda s: s.last_active or datetime.min.replace(tzinfo=timezone.utc))


_DEFAULT_ROOTS = (Path.home() / "code", Path.home() / "dev")


def resolve_project_dir(
    text: str, roots: Sequence[Path] = _DEFAULT_ROOTS
) -> tuple[str, str] | None:
    """Resolve spoken text to a direct child directory of one of the roots.

    On a name collision across roots, the earliest root in the list wins."""
    projects: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if path.is_dir():
                projects.setdefault(path.name, path)

    normalized, _number = _extract_number(_normalize(text))
    close = difflib.get_close_matches(normalized, projects.keys(), n=1, cutoff=_MATCH_CUTOFF)
    if not close:
        return None

    name = close[0]
    return name, str(projects[name])
