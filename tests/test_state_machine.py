from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock

from laris.state_machine import (
    PHASE_AWAITING_DICTATION,
    PHASE_AWAITING_PROJECT,
    PHASE_AWAITING_SEND,
    PHASE_IDLE,
    VoiceSession,
)


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


def _lina_session():
    return _FakeSession(
        name="lina", project="lina", tmux_pid=1, cwd="/tmp/lina",
        state="working", git_branch=None, tmux_name="lina",
    )


def _make_session(sessions=None):
    send_text = MagicMock()
    send_enter = MagicMock()
    vs = VoiceSession(
        get_sessions=lambda: sessions or [_lina_session()],
        send_text=send_text,
        send_enter=send_enter,
    )
    return vs, send_text, send_enter


def test_ignores_utterances_without_wake_phrase():
    vs, send_text, _ = _make_session()
    phase = vs.handle_utterance("que horas sao")
    assert phase == PHASE_IDLE
    send_text.assert_not_called()


def test_wake_phrase_moves_to_awaiting_project():
    vs, _, _ = _make_session()
    phase = vs.handle_utterance("ola kiris")
    assert phase == PHASE_AWAITING_PROJECT


def test_unmatched_project_resets_to_idle():
    vs, _, _ = _make_session()
    vs.handle_utterance("ola kiris")
    phase = vs.handle_utterance("xerox")
    assert phase == PHASE_IDLE


def test_unmatched_project_can_spawn_and_continue_to_dictation():
    spawned = _FakeSession(
        name="new-project", project="new-project", tmux_pid=2, cwd="/tmp/new-project",
        state="working", git_branch=None, tmux_name="new-project",
    )
    vs = VoiceSession(
        get_sessions=lambda: [],
        send_text=MagicMock(),
        send_enter=MagicMock(),
        spawn_and_target=lambda text: spawned,
    )

    vs.handle_utterance("ola kiris")
    phase = vs.handle_utterance("new project")

    assert phase == PHASE_AWAITING_DICTATION
    assert vs.matched_session == spawned


def test_unmatched_project_spawn_failure_resets_to_idle():
    vs = VoiceSession(
        get_sessions=lambda: [],
        send_text=MagicMock(),
        send_enter=MagicMock(),
        spawn_and_target=lambda text: None,
    )

    vs.handle_utterance("ola kiris")
    phase = vs.handle_utterance("missing project")

    assert phase == PHASE_IDLE
    assert vs.matched_session is None


def test_matched_project_moves_to_awaiting_dictation():
    vs, _, _ = _make_session()
    vs.handle_utterance("ola kiris")
    phase = vs.handle_utterance("lina")
    assert phase == PHASE_AWAITING_DICTATION
    assert vs.matched_session.name == "lina"


def test_dictation_sends_text_and_moves_to_awaiting_send():
    vs, send_text, send_enter = _make_session()
    vs.handle_utterance("ola kiris")
    vs.handle_utterance("lina")
    phase = vs.handle_utterance("cria um teste novo")
    assert phase == PHASE_AWAITING_SEND
    send_text.assert_called_once_with("lina", "cria um teste novo")
    send_enter.assert_not_called()


def test_send_confirmation_sends_enter_and_resets_to_idle():
    vs, _, send_enter = _make_session()
    vs.handle_utterance("ola kiris")
    vs.handle_utterance("lina")
    vs.handle_utterance("cria um teste novo")
    phase = vs.handle_utterance("manda")
    assert phase == PHASE_IDLE
    send_enter.assert_called_once_with("lina")
    assert vs.matched_session is None


def test_non_confirmation_after_dictation_resets_without_sending_enter():
    vs, _, send_enter = _make_session()
    vs.handle_utterance("ola kiris")
    vs.handle_utterance("lina")
    vs.handle_utterance("cria um teste novo")
    phase = vs.handle_utterance("obrigado")
    assert phase == PHASE_IDLE
    send_enter.assert_not_called()


class _FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _make_timed_session():
    clock = _FakeClock()
    send_text = MagicMock()
    vs = VoiceSession(
        get_sessions=lambda: [_lina_session()],
        send_text=send_text,
        send_enter=MagicMock(),
        now=clock,
    )
    return vs, send_text, clock


def test_expire_if_stale_resets_abandoned_phase():
    vs, _, clock = _make_timed_session()
    vs.handle_utterance("ola kiris")
    vs.handle_utterance("lina")
    assert vs.phase == PHASE_AWAITING_DICTATION

    clock.t += 31

    assert vs.expire_if_stale() is True
    assert vs.phase == PHASE_IDLE
    assert vs.matched_session is None


def test_expire_if_stale_is_noop_when_fresh_or_idle():
    vs, _, clock = _make_timed_session()
    assert vs.expire_if_stale() is False  # idle: nothing to expire

    vs.handle_utterance("ola kiris")
    clock.t += 5
    assert vs.expire_if_stale() is False  # fresh: keeps the phase
    assert vs.phase == PHASE_AWAITING_PROJECT


def test_stale_phase_does_not_leak_next_utterance_into_dictation():
    vs, send_text, clock = _make_timed_session()
    vs.handle_utterance("ola kiris")
    vs.handle_utterance("lina")

    clock.t += 31
    phase = vs.handle_utterance("axon")

    send_text.assert_not_called()
    assert phase == PHASE_IDLE


def _make_session_with_close(sessions=None):
    send_text = MagicMock()
    end_session = MagicMock()
    vs = VoiceSession(
        get_sessions=lambda: sessions or [_lina_session()],
        send_text=send_text,
        send_enter=MagicMock(),
        end_session=end_session,
    )
    return vs, send_text, end_session


def test_close_command_kills_matched_session_and_resets_to_idle():
    vs, send_text, end_session = _make_session_with_close()
    vs.handle_utterance("ola kiris")

    phase = vs.handle_utterance("fechar lina")

    end_session.assert_called_once_with("lina")
    send_text.assert_not_called()
    assert phase == PHASE_IDLE
    assert vs.matched_session is None


def test_close_command_tolerates_article_and_verb_variants():
    vs, _, end_session = _make_session_with_close()
    vs.handle_utterance("ola kiris")

    vs.handle_utterance("fecha o lina")

    end_session.assert_called_once_with("lina")


def test_close_command_with_unmatched_project_resets_without_killing():
    vs, _, end_session = _make_session_with_close()
    vs.handle_utterance("ola kiris")

    phase = vs.handle_utterance("fechar xerox")

    end_session.assert_not_called()
    assert phase == PHASE_IDLE


def test_close_verb_without_injected_end_session_falls_through_to_project_match():
    vs, _, _ = _make_session()  # no end_session wired
    vs.handle_utterance("ola kiris")

    phase = vs.handle_utterance("fechar xerox")

    assert phase == PHASE_IDLE


def test_unmatched_project_speaks_feedback():
    feedback = []
    vs = VoiceSession(
        get_sessions=lambda: [_lina_session()],
        send_text=MagicMock(),
        send_enter=MagicMock(),
        on_feedback=feedback.append,
    )
    vs.handle_utterance("ola kiris")

    vs.handle_utterance("xerox")

    assert feedback == ["não achei esse projeto"]


def test_unmatched_close_target_speaks_feedback():
    feedback = []
    vs = VoiceSession(
        get_sessions=lambda: [_lina_session()],
        send_text=MagicMock(),
        send_enter=MagicMock(),
        end_session=MagicMock(),
        on_feedback=feedback.append,
    )
    vs.handle_utterance("ola kiris")

    vs.handle_utterance("fechar xerox")

    assert feedback == ["não achei essa sessão"]


def test_matched_project_gives_no_feedback():
    feedback = []
    vs = VoiceSession(
        get_sessions=lambda: [_lina_session()],
        send_text=MagicMock(),
        send_enter=MagicMock(),
        on_feedback=feedback.append,
    )
    vs.handle_utterance("ola kiris")

    vs.handle_utterance("lina")

    assert feedback == []
