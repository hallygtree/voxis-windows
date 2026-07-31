import threading
import time
from dataclasses import dataclass
from datetime import datetime
from unittest.mock import MagicMock

import pytest

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


class _StopLoop(Exception):
    """Breaks daemon.run's infinite loop from a stubbed _wait_for_ptt."""


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

    assert typed == ["texto"] * 3
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

    assert typed == ["ok", "ok"], "the failing utterance is skipped, not fatal"
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
