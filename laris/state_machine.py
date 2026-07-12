"""Pure orchestration: feed transcribed utterances one at a time via
handle_utterance(), get back the current phase. No audio, no ML, no real
tmux calls here - those are injected as callables so this is
unit-testable with plain strings and fakes. See the design spec's Voice
layer flow for the exact state transitions this implements."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from laris.protocols import SessionLike
from laris.phrase_matching import (
    is_send_confirmation,
    match_close_phrase,
    match_wake_phrase,
)
from laris.project_matcher import match_project

PHASE_IDLE = "idle"
PHASE_AWAITING_PROJECT = "awaiting_project"
PHASE_AWAITING_DICTATION = "awaiting_dictation"
PHASE_AWAITING_SEND = "awaiting_send"

# An abandoned mid-flow phase (user walked away after "qual projeto?") must
# not capture the NEXT utterance days later as dictation into that session.
PHASE_TIMEOUT_SECONDS = 30.0


@dataclass
class VoiceSession:
    """State machine for one wake -> project -> dictate -> send cycle.
    get_sessions is called fresh on each project-name utterance (the
    session list can change between wake and dictation)."""

    get_sessions: Callable[[], list[SessionLike]]
    send_text: Callable[[str, str], None]
    send_enter: Callable[[str], None]
    spawn_and_target: Callable[[str], SessionLike | None] | None = None
    end_session: Callable[[str], None] | None = None
    on_feedback: Callable[[str], None] | None = None
    now: Callable[[], float] = time.monotonic
    phase: str = field(default=PHASE_IDLE, init=False)
    matched_session: SessionLike | None = field(default=None, init=False)
    _last_advance: float = field(default=0.0, init=False)

    def begin_command_flow(self) -> None:
        """External entry into the command flow (PTT skips the wake phrase).
        Stamps the clock - setting phase directly would leave _last_advance
        stale and expire_if_stale would kill the flow on its first utterance."""
        self.phase = PHASE_AWAITING_PROJECT
        self._last_advance = self.now()

    def expire_if_stale(self) -> bool:
        """Reset an abandoned mid-flow phase back to idle.
        Returns True only when a reset actually happened."""
        if self.phase == PHASE_IDLE:
            return False
        if self.now() - self._last_advance < PHASE_TIMEOUT_SECONDS:
            return False
        self.phase = PHASE_IDLE
        self.matched_session = None
        return True

    def handle_utterance(self, text: str) -> str:
        """Advance the state machine with one transcribed utterance.
        Returns the new phase (also available as self.phase)."""
        self.expire_if_stale()
        self._last_advance = self.now()

        if self.phase == PHASE_IDLE:
            if match_wake_phrase(text):
                self.phase = PHASE_AWAITING_PROJECT

        elif self.phase == PHASE_AWAITING_PROJECT:
            close_target = match_close_phrase(text) if self.end_session else None
            if close_target is not None:
                session = match_project(close_target, self.get_sessions())
                if session is not None:
                    self.end_session(session.tmux_name)
                elif self.on_feedback:
                    self.on_feedback("não achei essa sessão")
                # matched or not, a close utterance ends the flow
                self.phase = PHASE_IDLE
                self.matched_session = None
                return self.phase

            session = match_project(text, self.get_sessions())
            if session is None:
                session = self.spawn_and_target(text) if self.spawn_and_target else None
                if session is None:
                    # ponytail: no match resets to idle; retry requires a
                    # fresh wake phrase, no re-prompt loop (spec doesn't ask for one)
                    if self.on_feedback:
                        self.on_feedback("não achei esse projeto")
                    self.phase = PHASE_IDLE
                    self.matched_session = None
                else:
                    self.matched_session = session
                    self.phase = PHASE_AWAITING_DICTATION
            else:
                self.matched_session = session
                self.phase = PHASE_AWAITING_DICTATION

        elif self.phase == PHASE_AWAITING_DICTATION:
            self.send_text(self.matched_session.tmux_name, text)
            self.phase = PHASE_AWAITING_SEND

        elif self.phase == PHASE_AWAITING_SEND:
            if is_send_confirmation(text):
                self.send_enter(self.matched_session.tmux_name)
            self.phase = PHASE_IDLE
            self.matched_session = None

        return self.phase
