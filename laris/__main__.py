"""Standalone entrypoint: `python -m laris`. Dictation-only - no tmux
session backend, so "abrir/fechar <projeto>" utterances simply won't match
any session and reset to idle (see VoiceSession's own behavior for that
case). For the full tmux-integrated product, see claude-code-ops."""
from __future__ import annotations

from laris.state_machine import VoiceSession


def _make_voice_session() -> VoiceSession:
    return VoiceSession(get_sessions=lambda: [], send_text=lambda *_: None, send_enter=lambda *_: None)


def main() -> None:
    from laris import daemon

    daemon.run(make_voice_session=_make_voice_session)


if __name__ == "__main__":
    main()
