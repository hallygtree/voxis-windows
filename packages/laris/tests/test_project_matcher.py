from dataclasses import dataclass
from datetime import datetime, timezone

from laris.project_matcher import match_project


@dataclass(frozen=True)
class _FakeSession:
    name: str
    project: str
    tmux_pid: int
    cwd: str
    state: str
    git_branch: str | None
    tmux_name: str
    last_active: datetime | None = None


def _session(name, project, last_active=None):
    return _FakeSession(
        name=name, project=project, tmux_pid=1, cwd=f"/tmp/{project}",
        state="working", git_branch=None, tmux_name=name,
        last_active=last_active,
    )


def test_match_project_exact_name():
    sessions = [_session("lina", "lina"), _session("axon", "axon")]
    result = match_project("lina", sessions)
    assert result.name == "lina"


def test_match_project_tolerates_mistranscription():
    sessions = [_session("lina", "lina")]
    result = match_project("linha", sessions)
    assert result.name == "lina"


def test_match_project_returns_none_when_no_close_match():
    sessions = [_session("lina", "lina")]
    result = match_project("xerox", sessions)
    assert result is None


def test_match_project_disambiguates_by_spoken_number():
    sessions = [
        _session("lina", "lina"),
        _session("lina-2", "lina"),
    ]
    result = match_project("lina dois", sessions)
    assert result.name == "lina-2"


def test_match_project_defaults_to_most_recently_active():
    older = datetime(2026, 7, 6, 10, 0, tzinfo=timezone.utc)
    newer = datetime(2026, 7, 6, 11, 0, tzinfo=timezone.utc)
    sessions = [
        _session("lina", "lina", last_active=older),
        _session("lina-2", "lina", last_active=newer),
    ]
    result = match_project("lina", sessions)
    assert result.name == "lina-2"


def test_match_project_returns_none_for_empty_session_list():
    assert match_project("lina", []) is None
