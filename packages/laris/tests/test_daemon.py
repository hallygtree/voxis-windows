import threading
import time

import numpy as np
import pytest
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock

from laris.state_machine import (
    PHASE_AWAITING_DICTATION,
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


def _stub_agent_phrase_matcher(text: str) -> str | None:
    """Local stand-in for kiris.phrase_matching.match_agent_phrase
    (lives in the kiris repo - see Task 10). Strips a leading 'kiris '
    or 'ola kiris ' from the utterance so route_utterance's KIRIS branch
    can be exercised without importing the kiris package."""
    words = text.lower().split()
    if len(words) >= 2 and words[0] in {"ola", "oi"} and words[1] == "kiris":
        return " ".join(words[2:])
    if words and words[0] == "kiris":
        return " ".join(words[1:])
    return None


def _lina_session():
    return _FakeSession(
        name="lina", project="lina", tmux_pid=1, cwd="/tmp/lina",
        state="working", git_branch=None, tmux_name="lina",
    )


def _make_voice_session():
    send_text = MagicMock()
    end_session = MagicMock()
    vs = VoiceSession(
        get_sessions=lambda: [_lina_session()],
        send_text=send_text,
        send_enter=MagicMock(),
        end_session=end_session,
    )
    return vs, send_text, end_session


def test_plain_text_is_dictation(monkeypatch):
    from laris.daemon import route_utterance

    vs, send_text, _ = _make_voice_session()
    typer = MagicMock()

    phase = route_utterance("hello world", vs, typer)

    assert phase == PHASE_IDLE
    typer.assert_called_once_with("hello world")
    send_text.assert_not_called()


def test_open_verb_enters_command_flow(monkeypatch):
    from laris.daemon import route_utterance

    vs, _, _ = _make_voice_session()
    typer = MagicMock()

    phase = route_utterance("abrir lina", vs, typer)

    assert phase == PHASE_AWAITING_DICTATION
    assert vs.matched_session.name == "lina"
    typer.assert_not_called()


def test_close_verb_kills_session_without_typing(monkeypatch):
    from laris.daemon import route_utterance

    vs, _, end_session = _make_voice_session()
    typer = MagicMock()

    phase = route_utterance("fechar lina", vs, typer)

    assert phase == PHASE_IDLE
    end_session.assert_called_once_with("lina")
    typer.assert_not_called()


def test_mid_flow_utterance_continues_the_flow_not_dictation(monkeypatch):
    from laris.daemon import route_utterance

    vs, send_text, _ = _make_voice_session()
    typer = MagicMock()
    route_utterance("abrir lina", vs, typer)  # now awaiting dictation

    route_utterance("roda os testes", vs, typer)

    send_text.assert_called_once_with("lina", "roda os testes")
    typer.assert_not_called()


def test_live_amplitude_pusher_throttles(monkeypatch):
    import numpy as np

    from laris.daemon import _make_live_amplitude_pusher

    events = []

    class FakeQueue:
        def put(self, event):
            events.append(event)

    clock = {"t": 100.0}
    push = _make_live_amplitude_pusher(FakeQueue(), now=lambda: clock["t"])

    chunk = np.full((4,), 0.5, dtype=np.float32)
    push(chunk)
    push(chunk)  # same instant: throttled
    clock["t"] += 0.2
    push(chunk)

    assert len(events) == 2
    assert all(e.phase == "recording" for e in events)
    assert events[0].amplitude > 0


def test_live_amplitude_pusher_defaults_to_25hz():
    """Mic chunks land at ~31Hz; the orb should see nearly all of them -
    at the old 10Hz the deformation lagged visibly behind speech."""
    import numpy as np

    from laris.daemon import _make_live_amplitude_pusher

    events = []

    class FakeQueue:
        def put(self, event):
            events.append(event)

    clock = {"t": 100.0}
    push = _make_live_amplitude_pusher(FakeQueue(), now=lambda: clock["t"])

    chunk = np.full((4,), 0.5, dtype=np.float32)
    for _ in range(10):  # chunks every 50ms for half a second
        push(chunk)
        clock["t"] += 0.05

    assert len(events) == 10  # none throttled at 20Hz input


class _StubAssistant:
    def __init__(self):
        self.requests = []
        self.followups = []
        self.consume_followup = False

    def handle(self, request):
        self.requests.append(request)

    def handle_followup(self, text):
        self.followups.append(text)
        return self.consume_followup


def test_agent_name_routes_to_assistant_not_dictation():
    from laris.daemon import route_utterance

    vs, send_text, _ = _make_voice_session()
    typer = MagicMock()
    assistant = _StubAssistant()

    phase = route_utterance(
        "kiris abre o axon", vs, typer, assistant=assistant,
        agent_phrase_matcher=_stub_agent_phrase_matcher,
    )

    assert phase == PHASE_IDLE
    assert assistant.requests == ["abre o axon"]
    typer.assert_not_called()
    send_text.assert_not_called()


def test_kiris_phrase_is_plain_dictation_without_assistant():
    """Laris (pure transcriber): the agent's name is just words to type."""
    from laris.daemon import route_utterance

    vs, send_text, _ = _make_voice_session()
    typer = MagicMock()

    phase = route_utterance("kiris abre o axon", vs, typer, assistant=None)

    assert phase == PHASE_IDLE
    typer.assert_called_once_with("kiris abre o axon")
    send_text.assert_not_called()


def test_pending_confirmation_consumes_the_next_utterance():
    from laris.daemon import route_utterance

    vs, _, _ = _make_voice_session()
    typer = MagicMock()
    assistant = _StubAssistant()
    assistant.consume_followup = True

    phase = route_utterance("sim", vs, typer, assistant=assistant)

    assert phase == PHASE_IDLE
    assert assistant.followups == ["sim"]
    typer.assert_not_called()


def test_kiris_dispatch_routes_when_matcher_and_kiris_dispatch_present():
    from laris.daemon import route_utterance

    vs, _, _ = _make_voice_session()
    typer = MagicMock()
    dispatch_calls = []
    def stub_matcher(text): return "abre o axon"
    def stub_dispatch(text): dispatch_calls.append(text); return True

    phase = route_utterance(
        "kiris abre o axon", vs, typer,
        agent_phrase_matcher=stub_matcher,
        kiris_dispatch=stub_dispatch,
    )

    assert phase == PHASE_IDLE
    assert dispatch_calls == ["abre o axon"]
    typer.assert_not_called()


def test_kiris_dispatch_skipped_when_offline_returns_false():
    """When kiris_dispatch returns False (kiris offline/error), route_utterance
    falls through to plain dictation - the utterance is typed into the focused app."""
    from laris.daemon import route_utterance

    vs, _, _ = _make_voice_session()
    typer = MagicMock()
    def stub_matcher(text): return "abre o axon"
    def stub_dispatch_offline(text): return False

    phase = route_utterance(
        "kiris abre o axon", vs, typer,
        agent_phrase_matcher=stub_matcher,
        kiris_dispatch=stub_dispatch_offline,
    )

    assert phase == PHASE_IDLE
    # Utterance is typed as dictation (kiris offline -> fallback)
    typer.assert_called_once_with("kiris abre o axon")


def test_run_signals_ready_only_after_push_to_talk_started(monkeypatch):
    """The tray shows "Ditado ativo" off this signal. Firing it before
    ptt.start() would reintroduce the exact lie this work removes: a menu
    claiming dictation works while cmd_r does nothing."""
    from laris import daemon

    events = []

    class _FakeBackend:
        def warm(self):
            events.append("warm")

        def transcribe(self, audio, sample_rate):
            return ""

        def type_text(self, text):
            pass

        def make_overlay(self, url):
            return MagicMock()

        def make_ducker(self):
            return MagicMock()

    class _FakePtt:
        def __init__(self, key):
            self.pressed = MagicMock()
            self.hands_free = MagicMock()

        def start(self):
            events.append("ptt.start")

    class _StopTheLoop(Exception):
        pass

    def _stop(*_args, **_kwargs):
        raise _StopTheLoop

    monkeypatch.setattr("laris.platform.get_backend", lambda: _FakeBackend())
    monkeypatch.setattr("laris.hotkey.PushToTalk", _FakePtt)
    monkeypatch.setattr(daemon, "_wait_for_ptt", _stop)

    try:
        daemon.run(
            make_voice_session=lambda: MagicMock(),
            on_ready=lambda: events.append("ready"),
        )
    except _StopTheLoop:
        pass

    assert events == ["warm", "ptt.start", "ready"]


class _StopLoop(Exception):
    """Breaks out of run()'s infinite PTT loop once we've seen what we need."""


def _run_with_fakes(monkeypatch, mode):
    """Drive daemon.run() far enough to observe the loop's first iteration."""
    import threading

    import laris.config as config_mod
    import laris.daemon as daemon_mod
    import laris.hotkey as hotkey_mod
    import laris.platform as platform_mod

    class FakeBackend:
        def warm(self):
            pass

        def transcribe(self, audio, sample_rate):
            return ""

        def type_text(self, text):
            pass

        def make_overlay(self, url):
            return MagicMock()

        def make_ducker(self):
            return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()

        def start(self):
            pass

    monkeypatch.setattr(platform_mod, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)
    monkeypatch.setattr(config_mod, "MODE", mode)

    seen = {}

    def fake_wait(pressed, hands_free=None, on_tick=lambda: None):
        # the flag must already be set the first time the loop asks for input
        seen["armed_at_entry"] = hands_free is not None and hands_free.is_set()
        raise _StopLoop

    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", fake_wait)

    try:
        daemon_mod.run(make_voice_session=lambda: MagicMock())
    except _StopLoop:
        pass
    return seen


def test_ptt_mode_does_not_arm_hands_free(monkeypatch):
    """The default must still wait for a real key press, not a VAD session."""
    assert _run_with_fakes(monkeypatch, "ptt")["armed_at_entry"] is False


def test_a_push_to_talk_daemon_names_its_key_and_mode_when_ready(monkeypatch, capsys):
    import laris.config as config_mod

    monkeypatch.setattr(config_mod, "DICTATE_KEY", "cmd_r")
    _run_with_fakes(monkeypatch, "ptt")
    lines = [line for line in capsys.readouterr().out.splitlines() if "pronta" in line]

    assert lines == ["[Voice] Laris (transcritora) pronta, pura (VOICE_ASSISTANT=0, muda) - "
                     "PTT: cmd_r, modo: ptt"]


def test_each_hands_free_line_shows_the_audio_length_and_the_stt_time(monkeypatch, capsys):
    """Per-utterance latency is read off laris.log: a 1.5 s utterance that
    took 0.42 s to transcribe says both, in seconds."""
    import threading
    import types

    import numpy as np

    import laris.audio_capture as audio_mod
    import laris.daemon as daemon_mod
    import laris.platform as platform_mod

    clock = {"now": 100.0}

    class SlowBackend:
        def warm(self):
            pass

        def transcribe(self, audio, sample_rate):
            clock["now"] += 0.42
            return "teste de ditado"

        def type_text(self, text):
            pass

        def make_overlay(self, url):
            return MagicMock()

        def make_ducker(self):
            return MagicMock()

    class OneUtterance:
        def stream_utterances(self, should_stop, on_chunk=None):
            yield np.zeros(24000, dtype=np.float32), 16000  # 1.5 s at 16 kHz

    class ToggledOn:
        label, stop_hint = "toggle", "toggle again to stop"

        def __init__(self):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()
            self.hands_free.set()

        def start(self):
            pass

    trigger = ToggledOn()
    waits = iter([("hands_free", trigger.hands_free)])

    def fake_wait(pressed, hands_free=None, on_tick=lambda: None):
        try:
            return next(waits)
        except StopIteration:
            raise _StopLoop

    monkeypatch.setattr(platform_mod, "get_backend", lambda: SlowBackend())
    monkeypatch.setattr(audio_mod, "VadCapture", OneUtterance)
    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", fake_wait)
    monkeypatch.setattr(daemon_mod, "time",
                        types.SimpleNamespace(monotonic=lambda: clock["now"], sleep=lambda s: None))

    try:
        daemon_mod.run(make_voice_session=lambda: MagicMock(), trigger=trigger)
    except _StopLoop:
        pass
    lines = [line for line in capsys.readouterr().out.splitlines()
             if line.startswith("[Voice] hands-free: ")]

    assert lines == ["[Voice] hands-free: 'teste de ditado' (audio=1.5s, stt=0.42s, amp=0.0000)"]


def test_parent_watchdog_only_fires_for_a_tray_spawned_daemon(monkeypatch):
    """A daemon started by hand in a terminal has no VOXIS_PARENT_PID and must
    never be killed by this - the tray deliberately leaves external daemons
    alone. A malformed value is ignored for the same reason."""
    import os

    from laris.daemon import _parent_gone

    monkeypatch.delenv("VOXIS_PARENT_PID", raising=False)
    assert _parent_gone() is False

    monkeypatch.setenv("VOXIS_PARENT_PID", str(os.getppid()))
    assert _parent_gone() is False

    monkeypatch.setenv("VOXIS_PARENT_PID", "not-a-pid")
    assert _parent_gone() is False

    monkeypatch.setenv("VOXIS_PARENT_PID", str(os.getppid() + 1))
    assert _parent_gone() is True


def test_run_exits_when_the_tray_that_spawned_it_dies(monkeypatch):
    """Force Quit, a crash or a logout never reaches the tray's "Sair" handler,
    so nothing signalled the daemon: one was found still holding the model, the
    mic and a keyboard listener six days after its tray had gone."""
    import threading

    import pytest

    import laris.config as config_mod
    import laris.daemon as daemon_mod
    import laris.hotkey as hotkey_mod
    import laris.platform as platform_mod

    class FakeBackend:
        def warm(self):
            pass

        def transcribe(self, audio, sample_rate):
            return ""

        def type_text(self, text):
            pass

        def make_overlay(self, url):
            return MagicMock()

        def make_ducker(self):
            return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()  # never pressed: only the tick runs
            self.hands_free = threading.Event()

        def start(self):
            pass

    def fake_wait(pressed, hands_free=None, on_tick=lambda: None):
        on_tick()  # the watchdog rides the tick the idle loop already runs
        raise _StopLoop  # reached only if the watchdog stayed silent

    monkeypatch.setattr(platform_mod, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)
    monkeypatch.setattr(config_mod, "MODE", "ptt")
    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", fake_wait)
    monkeypatch.setenv("VOXIS_PARENT_PID", "999999")  # a tray that is not our parent

    with pytest.raises(SystemExit):
        daemon_mod.run(make_voice_session=lambda: MagicMock())


def test_boot_refuses_to_start_beside_a_live_daemon(monkeypatch):
    """A second daemon can't bind :8421, but it still starts its own keyboard
    listener: one key press then records and types the utterance twice."""
    import laris.__main__ as main_mod
    from laris import peer_discovery

    monkeypatch.setattr(peer_discovery, "peer_url", lambda name: "http://127.0.0.1:8421")
    monkeypatch.setattr(peer_discovery, "peer_token", lambda name: "abc")

    class _Ok:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    assert main_mod._daemon_already_running(http_get=lambda *a, **k: _Ok()) == (
        "http://127.0.0.1:8421"
    )


def test_boot_proceeds_when_the_recorded_daemon_is_gone(monkeypatch):
    """peers.json outlives the daemon that wrote it - a stale entry must not
    block the next boot."""
    import laris.__main__ as main_mod
    from laris import peer_discovery

    monkeypatch.setattr(peer_discovery, "peer_url", lambda name: "http://127.0.0.1:8421")
    monkeypatch.setattr(peer_discovery, "peer_token", lambda name: "abc")

    def refused(*_args, **_kwargs):
        raise OSError("connection refused")

    assert main_mod._daemon_already_running(http_get=refused) is None


def _typed_in_hands_free_sessions(monkeypatch, sessions):
    """What the backend pastes when the daemon runs one hands-free session per
    entry of `sessions`, each a list of transcriptions in utterance order."""
    import threading

    import numpy as np

    import laris.audio_capture as audio_mod
    import laris.daemon as daemon_mod
    import laris.platform as platform_mod

    texts = iter(t for session in sessions for t in session)
    typed = []

    class Backend:
        def warm(self):
            pass

        def transcribe(self, audio, sample_rate):
            return next(texts)

        def type_text(self, text):
            typed.append(text)

        def make_overlay(self, url):
            return MagicMock()

        def make_ducker(self):
            return MagicMock()

    lengths = iter(len(session) for session in sessions)

    class Utterances:
        def stream_utterances(self, should_stop, on_chunk=None):
            for _ in range(next(lengths)):
                yield np.zeros(16000, dtype=np.float32), 16000

    class ToggledOn:
        label, stop_hint = "toggle", "toggle again to stop"

        def __init__(self):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()
            self.hands_free.set()

        def start(self):
            pass

    trigger = ToggledOn()
    waits = iter([("hands_free", trigger.hands_free)] * len(sessions))

    def fake_wait(pressed, hands_free=None, on_tick=lambda: None):
        try:
            return next(waits)
        except StopIteration:
            raise _StopLoop

    monkeypatch.setattr(platform_mod, "get_backend", lambda: Backend())
    monkeypatch.setattr(audio_mod, "VadCapture", Utterances)
    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", fake_wait)
    try:
        daemon_mod.run(make_voice_session=lambda: MagicMock(), trigger=trigger)
    except _StopLoop:
        pass
    return typed


def test_utterances_of_one_hands_free_session_are_pasted_a_space_apart(monkeypatch):
    """Without it, two sentences dictated in a row landed glued:
    "falhas.Faz o commit" (owner's dictation test, 2026-10-15)."""
    typed = _typed_in_hands_free_sessions(
        monkeypatch, [["Roda o pytest.", "Faz o commit.", "Pode seguir."]])

    assert "".join(typed) == "Roda o pytest. Faz o commit. Pode seguir."


def test_a_new_hands_free_session_starts_without_a_space(monkeypatch):
    typed = _typed_in_hands_free_sessions(monkeypatch, [["Roda o pytest."], ["Pode seguir."]])

    assert typed == ["Roda o pytest.", "Pode seguir."]


# --- Windows fork: live mode, background warm, orb state ---


def test_hands_free_unavailable_does_not_kill_the_daemon(monkeypatch, capsys):
    """The torch-free Windows bundle has no silero-vad, so VadCapture() exits
    the process. A double-tap of the PTT key must not take plain dictation
    down with it - regression for the daemon dying on a documented gesture."""
    import laris.audio_capture as audio_capture
    import laris.config as config_mod
    import laris.daemon as daemon_mod
    import laris.hotkey as hotkey_mod
    import laris.platform as platform_mod

    class FakeBackend:
        def warm(self): pass
        def transcribe(self, audio, sample_rate): return ""
        def type_text(self, text): pass
        def make_overlay(self, url, state=None): return MagicMock()
        def make_ducker(self): return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()

        def start(self): pass

    def no_silero(*args, **kwargs):
        raise SystemExit("[Audio] silero-vad not installed: pip install silero-vad")

    monkeypatch.setattr(platform_mod, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)
    monkeypatch.setattr(audio_capture, "VadCapture", no_silero)
    # the gesture only reaches the loop when the setting permits it
    monkeypatch.setattr(config_mod, "MODE", "always_on")

    rounds = {"n": 0}

    def fake_wait(pressed, hands_free=None, on_tick=lambda: None):
        rounds["n"] += 1
        if rounds["n"] == 1:
            hands_free.set()
            return "hands_free", hands_free
        raise _StopLoop  # the loop survived round 1: that is the assertion

    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", fake_wait)

    with pytest.raises(_StopLoop):
        daemon_mod.run(make_voice_session=lambda: MagicMock())

    assert "hands-free unavailable" in capsys.readouterr().out
    assert rounds["n"] == 2



def test_always_on_permits_the_gesture_without_starting_a_session(monkeypatch):
    """ASSISTANT_MODE=always_on (the tray 'Hands-free' checkbox) permits the
    double-tap; it does not start listening. Arming at boot was harmless while
    hands-free did not work, but now it would mean the machine starts
    transcribing into whatever is focused the moment the app comes up."""
    import laris.config as config_mod
    import laris.daemon as daemon_mod
    import laris.hotkey as hotkey_mod
    import laris.platform as platform_mod

    class FakeBackend:
        def warm(self): pass
        def transcribe(self, audio, sample_rate): return ""
        def type_text(self, text): pass
        def make_overlay(self, url, state=None): return MagicMock()
        def make_ducker(self): return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()

        def start(self): pass

    monkeypatch.setattr(platform_mod, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)
    monkeypatch.setattr(config_mod, "MODE", "always_on")

    seen = {}

    def fake_wait(pressed, hands_free=None, on_tick=lambda: None):
        # the gesture is wired up (not None) but nothing is armed yet
        seen["gesture_wired"] = hands_free is not None
        seen["armed_at_entry"] = hands_free is not None and hands_free.is_set()
        raise _StopLoop

    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", fake_wait)

    with pytest.raises(_StopLoop):
        daemon_mod.run(make_voice_session=lambda: MagicMock())

    assert seen["gesture_wired"] is True
    assert seen["armed_at_entry"] is False



def test_ptt_mode_ignores_the_gesture_entirely(monkeypatch):
    """With the default ASSISTANT_MODE=ptt the double-tap must do nothing at
    all - the loop never even looks at the flag, so a stray gesture cannot
    open a microphone the user did not ask for."""
    import laris.config as config_mod
    import laris.daemon as daemon_mod
    import laris.hotkey as hotkey_mod
    import laris.platform as platform_mod

    class FakeBackend:
        def warm(self): pass
        def transcribe(self, audio, sample_rate): return ""
        def type_text(self, text): pass
        def make_overlay(self, url, state=None): return MagicMock()
        def make_ducker(self): return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()

        def start(self): pass

    monkeypatch.setattr(platform_mod, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)
    monkeypatch.setattr(config_mod, "MODE", "ptt")

    seen = {}

    def fake_wait(pressed, hands_free=None, on_tick=lambda: None):
        seen["gesture_wired"] = hands_free is not None
        raise _StopLoop

    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", fake_wait)

    with pytest.raises(_StopLoop):
        daemon_mod.run(make_voice_session=lambda: MagicMock())

    assert seen["gesture_wired"] is False



def test_mode_flips_live_without_restarting_the_daemon(monkeypatch):
    """The tray used to restart the engine on every hands-free toggle, which
    tore down the orb window and reloaded the whisper model - it looked like a
    crash. The mode is now read every pass of the loop, so POST /mode moving
    the shared ModeState is enough."""
    import laris.daemon as daemon_mod
    import laris.hotkey as hotkey_mod
    import laris.platform as platform_mod
    from laris.runtime_mode import ModeState

    class FakeBackend:
        def warm(self): pass
        def transcribe(self, audio, sample_rate): return ""
        def type_text(self, text): pass
        def make_overlay(self, url, state=None): return MagicMock()
        def make_ducker(self): return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()

        def start(self): pass

    monkeypatch.setattr(platform_mod, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)

    mode_state = ModeState("ptt")
    wired = []

    def fake_wait(pressed, hands_free=None, on_tick=lambda: None):
        wired.append(hands_free is not None)
        if len(wired) == 1:
            mode_state.set("always_on")  # what POST /mode does
            return "dictate", threading.Event()  # one harmless PTT pass
        raise _StopLoop

    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", fake_wait)
    # the loop imports this inside the body, so patch it at the source module
    import laris.audio_capture as capture_mod
    monkeypatch.setattr(capture_mod, "record_while",
                        lambda *a, **k: np.zeros(0, dtype=np.float32))

    with pytest.raises(_StopLoop):
        daemon_mod.run(make_voice_session=lambda: MagicMock(), mode_state=mode_state)

    assert wired == [False, True], "the same process must see the new mode"



def test_gesture_landing_while_off_does_not_queue_a_session(monkeypatch):
    """A double-tap while hands-free is disabled must be dropped, not held. If
    it survived, switching the toggle on would immediately open the microphone
    - the exact 'starts listening on its own' hazard the gesture prevents."""
    import laris.daemon as daemon_mod
    import laris.hotkey as hotkey_mod
    import laris.platform as platform_mod
    from laris.runtime_mode import ModeState

    class FakeBackend:
        def warm(self): pass
        def transcribe(self, audio, sample_rate): return ""
        def type_text(self, text): pass
        def make_overlay(self, url, state=None): return MagicMock()
        def make_ducker(self): return MagicMock()

    ptt_ref = {}

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()
            self.hands_free.set()  # stray double-tap from while it was off
            ptt_ref["ptt"] = self

        def start(self): pass

    monkeypatch.setattr(platform_mod, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)

    def fake_wait(pressed, hands_free=None, on_tick=lambda: None):
        raise _StopLoop

    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", fake_wait)

    with pytest.raises(_StopLoop):
        daemon_mod.run(make_voice_session=lambda: MagicMock(),
                       mode_state=ModeState("ptt"))

    assert not ptt_ref["ptt"].hands_free.is_set()



def test_daemon_run_accepts_orb_state_parameter(monkeypatch):
    """Verify that daemon.run() accepts orb_state parameter."""
    import laris.daemon as daemon_mod
    import laris.platform as platform_mod
    import laris.hotkey as hotkey_mod
    from laris.orb_state import OrbStateManager

    class FakeBackend:
        def warm(self): pass
        def transcribe(self, audio, sample_rate): return ""
        def type_text(self, text): pass
        def make_overlay(self, url, state=None): return MagicMock()
        def make_ducker(self): return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()
        def start(self): pass

    def stop_after_first(pressed, hands_free=None, on_tick=lambda: None):
        raise _StopLoop

    monkeypatch.setattr(platform_mod, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)
    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", stop_after_first)

    orb_state = OrbStateManager()
    assert orb_state.snapshot().ready is False

    with pytest.raises(_StopLoop):
        daemon_mod.run(
            make_voice_session=lambda: MagicMock(),
            orb_state=orb_state,
        )

    # warm() now runs on a background thread so the hotkey does not wait for
    # the model, so poll instead of asserting on thread scheduling luck.
    assert _wait_until(lambda: orb_state.snapshot().ready is True)



def _wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False



def test_hotkey_is_live_before_the_model_finishes_loading(monkeypatch):
    """The point of warming on a thread: loading the model costs seconds, and
    the PTT key used to be dead for all of them. Holding the key during boot
    must record, not be swallowed."""
    import laris.daemon as daemon_mod
    import laris.platform as platform_mod
    import laris.hotkey as hotkey_mod

    still_loading = threading.Event()
    events = []

    class SlowBackend:
        warms_in_background = True  # opts in, as the Windows backend does

        def warm(self):
            events.append("warm-start")
            still_loading.wait(5)          # model not ready yet
            events.append("warm-done")
        def transcribe(self, audio, sample_rate): return ""
        def type_text(self, text): pass
        def make_overlay(self, url, state=None): return MagicMock()
        def make_ducker(self): return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()
        def start(self): events.append("hotkey")

    def stop_at_loop(*a, **k):
        events.append("loop")
        raise _StopLoop

    monkeypatch.setattr(platform_mod, "get_backend", lambda: SlowBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)
    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", stop_at_loop)

    try:
        with pytest.raises(_StopLoop):
            daemon_mod.run(make_voice_session=lambda: MagicMock())
        # The hotkey is hooked and the loop is accepting input while warm() is
        # STILL blocked. "warm-done" must be absent: if loading ran inline, it
        # would have had to finish before the loop was ever reached, which is
        # exactly the old behaviour this guards against.
        assert "hotkey" in events and "loop" in events
        assert "warm-done" not in events
        assert events.index("hotkey") < events.index("loop")
    finally:
        still_loading.set()



def test_ready_is_not_reported_when_no_backend_is_usable(monkeypatch):
    """Regression: a machine where every rung of the STT chain failed still got
    told "ready", so the tray enabled dictation that returned "" forever."""
    import laris.daemon as daemon_mod
    import laris.platform as platform_mod
    import laris.hotkey as hotkey_mod
    from laris.orb_state import OrbStateManager

    warmed = threading.Event()

    class DeadBackend:
        def warm(self): warmed.set()
        def stt_usable(self): return False
        def transcribe(self, audio, sample_rate): return ""
        def type_text(self, text): pass
        def make_overlay(self, url, state=None): return MagicMock()
        def make_ducker(self): return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()
        def start(self): pass

    monkeypatch.setattr(platform_mod, "get_backend", lambda: DeadBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)
    monkeypatch.setattr(daemon_mod, "_wait_for_ptt",
                        lambda *a, **k: (_ for _ in ()).throw(_StopLoop()))

    orb_state = OrbStateManager()
    with pytest.raises(_StopLoop):
        daemon_mod.run(make_voice_session=lambda: MagicMock(), orb_state=orb_state)

    assert warmed.wait(5), "warm() should still have been attempted"
    assert _wait_until(lambda: orb_state.snapshot().ready is True, timeout=0.5) is False



def test_daemon_run_without_orb_state_behaves_as_before(monkeypatch):
    """Verify that daemon.run() without orb_state still works."""
    import laris.daemon as daemon_mod
    import laris.platform as platform_mod
    import laris.hotkey as hotkey_mod

    class FakeBackend:
        def warm(self): pass
        def transcribe(self, audio, sample_rate): return ""
        def type_text(self, text): pass
        def make_overlay(self, url, state=None): return MagicMock()
        def make_ducker(self): return MagicMock()

    class FakePTT:
        def __init__(self, key):
            self.pressed = threading.Event()
            self.hands_free = threading.Event()
        def start(self): pass

    def stop_after_first(pressed, hands_free=None, on_tick=lambda: None):
        raise _StopLoop

    monkeypatch.setattr(platform_mod, "get_backend", lambda: FakeBackend())
    monkeypatch.setattr(hotkey_mod, "PushToTalk", FakePTT)
    monkeypatch.setattr(daemon_mod, "_wait_for_ptt", stop_after_first)

    # Should not raise
    with pytest.raises(_StopLoop):
        daemon_mod.run(make_voice_session=lambda: MagicMock())  # orb_state=None



def _hands_free_parts(utterances, transcribe=None):
    """The five collaborators _run_hands_free_session drives."""
    import numpy as np

    class FakeVad:
        def stream_utterances(self, should_stop=None, on_chunk=None):
            for audio in utterances:
                if should_stop is not None and should_stop():
                    return
                yield np.asarray(audio, dtype=np.float32), 16000

    class FakeStt:
        def transcribe(self, audio, sample_rate):
            if transcribe is not None:
                return transcribe(audio)
            return "texto"

    typed = []
    overlay = MagicMock()
    ducker = MagicMock()
    return FakeVad(), FakeStt(), typed.append, overlay, ducker, typed



def test_hands_free_session_types_every_utterance():
    """Nothing covered this function before, and it is the one that writes into
    whatever the user has focused."""
    import queue

    import laris.daemon as daemon_mod

    vad, stt, typer, overlay, ducker, typed = _hands_free_parts([[0.1] * 16000] * 3)
    active = threading.Event()
    active.set()

    daemon_mod._run_hands_free_session(
        vad, stt, typer, overlay, queue.Queue(), active, ducker=ducker
    )

    # the session puts a space between its utterances, none before the first
    assert typed == ["texto", " texto", " texto"]
    overlay.show.assert_called_once_with("dictate")
    overlay.hide.assert_called_once()
    ducker.duck.assert_called_once()
    ducker.restore.assert_called_once()



def test_one_bad_utterance_does_not_end_the_hands_free_session():
    """A transcription failure mid-session must cost that utterance, not the
    session - otherwise one hiccup silently drops the user back to PTT."""
    import queue

    import laris.daemon as daemon_mod

    calls = {"n": 0}

    def flaky(_audio):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("gpu hiccup")
        return "ok"

    vad, stt, typer, overlay, ducker, typed = _hands_free_parts(
        [[0.1] * 16000] * 3, transcribe=flaky
    )
    active = threading.Event()
    active.set()

    daemon_mod._run_hands_free_session(
        vad, stt, typer, overlay, queue.Queue(), active, ducker=ducker
    )

    assert typed == ["ok", " ok"], "the failing utterance is skipped, not fatal"
    overlay.hide.assert_called_once()



def test_hands_free_session_stops_when_the_flag_clears():
    """A single key press clears the flag; the session must notice and end."""
    import queue

    import laris.daemon as daemon_mod

    vad, stt, typer, overlay, ducker, typed = _hands_free_parts([[0.1] * 16000] * 3)
    active = threading.Event()   # already clear: stop before the first yield

    daemon_mod._run_hands_free_session(
        vad, stt, typer, overlay, queue.Queue(), active, ducker=ducker
    )

    assert typed == []
    overlay.hide.assert_called_once()

