"""LARIS's PTT / hands-free / always-on daemon loop. Panel-agnostic: takes
pre-built VoiceSession + optional assistant as factories, so this module
never imports tmux or session-registry code - see claude-code-ops's
backend/main.py for the composition root that builds those factories."""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable

from laris import config
from laris.amplitude import compute_amplitude
from laris.events import VoiceEvent
from laris.protocols import AssistantProtocol
from laris.state_machine import PHASE_IDLE, VoiceSession


def route_utterance(
    text: str,
    voice_session: VoiceSession,
    typer: Callable[[str], None],
    assistant: AssistantProtocol | None = None,
    agent_phrase_matcher: Callable[[str], str | None] | None = None,
    kiris_dispatch: Callable[[str], bool] | None = None,
) -> str:
    """One PTT key, intent comes from the utterance itself: a pending
    assistant confirmation consumes the utterance first, "kiris <pedido>"
    goes to the LLM assistant (in-process AssistantProtocol OR
    kiris_dispatch HTTP callback for the three-process daemon), mid-flow
    speech continues the command flow, "abrir/fechar <projeto>" enters it,
    anything else is dictation into the focused app."""
    from laris.phrase_matching import match_close_phrase, match_open_phrase

    voice_session.expire_if_stale()
    if assistant is not None and assistant.handle_followup(text):
        return PHASE_IDLE
    if voice_session.phase != PHASE_IDLE:
        return voice_session.handle_utterance(text)

    agent_request = agent_phrase_matcher(text) if agent_phrase_matcher else None
    if agent_request is not None:
        if kiris_dispatch is not None:
            # Three-process mode: POST to kiris /ask. On True, utterance consumed.
            # On False (kiris offline/error), FALL THROUGH to dictation so the
            # user's spoken "kiris abre o axon" is typed as plain words instead
            # of being silently dropped.
            if kiris_dispatch(agent_request):
                return PHASE_IDLE
        elif assistant is not None:
            # In-process composition mode (kept for backward compat and dev tests)
            assistant.handle(agent_request)
            return PHASE_IDLE

    open_target = match_open_phrase(text)
    if open_target is not None:
        voice_session.begin_command_flow()
        return voice_session.handle_utterance(open_target)
    if match_close_phrase(text) is not None:
        voice_session.begin_command_flow()
        return voice_session.handle_utterance(text)

    typer(text)
    return PHASE_IDLE


def _make_live_amplitude_pusher(voice_queue, now: Callable[[], float] = time.monotonic, min_interval: float = 0.04) -> Callable:
    """Feeds the orb ~25Hz mic amplitude while capturing - without this the
    orb only moves once per utterance and looks frozen mid-speech."""
    last = {"t": float("-inf")}

    def push(chunk) -> None:
        t = now()
        if t - last["t"] < min_interval:
            return
        last["t"] = t
        voice_queue.put(VoiceEvent(phase="recording", amplitude=compute_amplitude(chunk)))

    return push


def _parent_gone() -> bool:
    """True when the tray that spawned us has died.

    Only the tray's "Sair" ever signalled the daemon, so a Force Quit, a crash
    or a logout left a full daemon - model, mic, keyboard listener - running
    with nothing able to stop it; one was found six days after its tray. The
    tray passes its own pid in VOXIS_PARENT_PID, and losing it reparents us. A
    daemon started by hand has no such variable and is never touched by this.
    """
    spawner = os.environ.get("VOXIS_PARENT_PID")
    if not spawner:
        return False
    try:
        return os.getppid() != int(spawner)
    except ValueError:
        return False  # malformed env is not a reason to kill dictation


def _wait_for_ptt(pressed, hands_free=None, on_tick=lambda: None):
    while True:
        if hands_free is not None and hands_free.is_set():
            return "hands_free", hands_free
        if pressed.is_set():
            return "dictate", pressed
        on_tick()
        time.sleep(0.05)


def _run_hands_free_session(vad, stt, typer, overlay, voice_queue, active, ducker=None,
                            stop_hint="tap the dictate key to stop"):
    overlay.show("dictate")
    voice_queue.put(VoiceEvent(phase="recording", amplitude=0.15))
    if ducker is not None:
        ducker.duck()
    print(f"[Voice] hands-free ON ({stop_hint})")
    separator = ""  # a space between the session's utterances, none before the first
    try:
        for audio, sample_rate in vad.stream_utterances(
            should_stop=lambda: not active.is_set(),
            on_chunk=_make_live_amplitude_pusher(voice_queue),
        ):
            try:
                amplitude = compute_amplitude(audio)
                started = time.monotonic()
                text = stt.transcribe(audio, sample_rate)
                stt_seconds = time.monotonic() - started
                if text:
                    typer(separator + text)
                    separator = " "
                    print(f"[Voice] hands-free: {text!r} (audio={len(audio) / sample_rate:.1f}s, "
                          f"stt={stt_seconds:.2f}s, amp={amplitude:.4f})")
                voice_queue.put(VoiceEvent(phase="recording", amplitude=amplitude))
            except Exception as exc:  # noqa: BLE001 - one bad utterance must not end the session
                print(f"[Voice] {exc!r} (ignoring this utterance, hands-free keeps running)")
    except Exception as exc:  # noqa: BLE001 - mic/stream failure ends the session, not the loop
        print(f"[Voice] {exc!r} (hands-free session aborted)")
        active.clear()
    finally:
        if ducker is not None:
            ducker.restore()
        overlay.hide()
        voice_queue.put(VoiceEvent(phase=PHASE_IDLE, amplitude=0.0))
        print("[Voice] hands-free OFF")


def run(
    make_voice_session: Callable[[], VoiceSession],
    make_assistant: Callable[[], AssistantProtocol | None] = lambda: None,
    agent_phrase_matcher: Callable[[str], str | None] | None = None,
    kiris_dispatch: Callable[[str], bool] | None = None,
    voice_queue=None,
    overlay_url: str = "",
    on_ready: Callable[[], None] | None = None,
    trigger=None,
    orb_state=None,
    mode_state=None,
) -> None:
    """Runs the PTT voice loop on the calling thread - callers run this on a
    background daemon thread (see claude-code-ops's backend/main.py).

    trigger: anything with `pressed`/`hands_free` events, `start()`, and
    `label`/`stop_hint` strings for the log. Defaults to the PushToTalk key
    listener; Linux passes a ToggleTrigger, since Wayland gives the process
    no global key events.

    orb_state: an OrbStateManager the server exposes over /overlay/state, for
    a tray that draws the orb in its own window (Windows). mode_state: the live
    ASSISTANT_MODE, flipped over POST /mode without restarting the daemon."""
    from laris.platform import get_backend

    if voice_queue is None:
        import queue
        voice_queue = queue.Queue()

    if mode_state is None:
        from laris.runtime_mode import ModeState
        mode_state = ModeState(config.MODE)

    backend = get_backend()
    # A backend whose model load takes long enough to matter (Windows: a
    # whisper.cpp server, maybe a first-run download) opts into warming on a
    # background thread, so the key below is live at once and a press during
    # boot records normally while only the transcription waits. The others
    # warm here, on the thread that will transcribe: mlx ties its GPU streams
    # to the thread that created them.
    warm_in_background = getattr(backend, "warms_in_background", False)
    if not warm_in_background:
        backend.warm()
    stt = backend
    type_text = backend.type_text
    voice_session = make_voice_session()
    assistant = make_assistant()
    # Windows draws the orb in a tray window that reads orb_state over HTTP,
    # and publishes boot progress to it; backends that draw their own orb
    # have no such hook.
    attach = getattr(backend, "attach_orb_state", None)
    if attach is not None and orb_state is not None:
        attach(orb_state)
    overlay = backend.make_overlay(overlay_url)
    ducker = backend.make_ducker()
    if trigger is None:
        from laris.hotkey import PushToTalk
        trigger = PushToTalk(config.DICTATE_KEY)
        trigger_label = f"PTT: {config.DICTATE_KEY}"
        stop_hint = "tap the dictate key to stop"
        mode = f", modo: {config.MODE}"
        # the double-tap is the only way into hands-free, and ASSISTANT_MODE
        # decides whether it is honoured
        gesture_gated = True
    else:
        trigger_label, stop_hint = trigger.label, trigger.stop_hint
        # no key to hold: "ptt" would name a mode this trigger does not have
        mode = "" if config.MODE == "ptt" else f", modo: {config.MODE}"
        # a toggle trigger has no push-to-talk to fall back on: its toggle is
        # the user's explicit request for hands-free, whatever the mode says
        gesture_gated = False
    ptt = trigger
    ptt.start()

    def _report_ready():
        # Backends that can fail every rung of their chain say so, and the tray
        # must not advertise dictation that will silently return "" forever.
        usable = getattr(backend, "stt_usable", None)
        if usable is not None and not usable():
            print("[Voice] transcricao indisponivel - o tray nao vai marcar pronto")
            if orb_state is not None:
                # The label is the only place a user sees this; leaving it on
                # the last progress step would read as "still loading" forever.
                orb_state.set_status("transcricao indisponivel")
            return
        if orb_state is not None:
            # ready first: the label only shows status while not ready, so this
            # order gives one visible transition instead of two.
            orb_state.set_ready(True)
            orb_state.set_status(None)
        # only now is dictation real: the model is loaded and the key listener
        # is attached. The tray polls this to stop claiming "Ditado" during the
        # seconds it takes to get here.
        if on_ready is not None:
            on_ready()

    if warm_in_background:
        def _warm_backend():
            started = time.monotonic()
            backend.warm()
            print(f"[Voice] modelo pronto em {time.monotonic() - started:.1f}s")
            _report_ready()

        threading.Thread(target=_warm_backend, name="laris-warm", daemon=True).start()
    else:
        _report_ready()
    vad = None
    vad_unavailable = False
    # ASSISTANT_MODE=always_on (the tray "Hands-free" checkbox) permits the
    # double-tap; it does not start a session. Booting straight into hands-free
    # would mean the machine starts listening and typing into whatever happens
    # to be focused the moment the app comes up. The double-tap is the intent
    # signal.
    kiris = "com Kiris (assistente)" if assistant else "pura (VOICE_ASSISTANT=0, muda)"
    print(
        f"[Voice] Laris (transcritora) pronta, {kiris} - "
        f"{trigger_label}{mode}"
    )

    def _reset_orb_if_stale():
        if _parent_gone():
            raise SystemExit("[Laris] the tray that started this daemon is gone - exiting")
        if voice_session.expire_if_stale():
            voice_queue.put(VoiceEvent(phase=PHASE_IDLE, amplitude=0.0))

    while True:
        # Read the mode every pass, not once at boot: the tray flips it over
        # HTTP (POST /mode) and used to have to restart the whole engine.
        if not gesture_gated or mode_state.hands_free_allowed:
            hands_free_gesture = ptt.hands_free
        else:
            # A double-tap landing while hands-free is off must not queue a
            # session that fires the moment it is switched on - that is the
            # "starts listening on its own" hazard the gesture exists to avoid.
            ptt.hands_free.clear()
            hands_free_gesture = None
        kind, pressed = _wait_for_ptt(ptt.pressed, hands_free=hands_free_gesture, on_tick=_reset_orb_if_stale)
        if kind == "hands_free":
            # Constructed on first use, and still guarded: a VAD that cannot
            # load must not take the daemon down with it, because that would
            # kill plain dictation too. SystemExit is spelled out because the
            # torch path raises it rather than a plain Exception.
            if vad is None and not vad_unavailable:
                try:
                    from laris.audio_capture import VadCapture
                    vad = VadCapture()
                except (Exception, SystemExit) as exc:  # noqa: BLE001
                    vad_unavailable = True
                    print(
                        f"[Voice] hands-free unavailable ({exc}); "
                        "push-to-talk keeps working. Hold the key to dictate."
                    )
            if vad is None:
                # clear it, or _wait_for_ptt hands it straight back and spins
                ptt.hands_free.clear()
                continue
            _run_hands_free_session(vad, stt, type_text, overlay, voice_queue, pressed, ducker=ducker,
                                    stop_hint=stop_hint)
            continue

        from laris.audio_capture import record_while

        phase, amplitude = voice_session.phase, 0.0
        overlay.show(kind)
        voice_queue.put(VoiceEvent(phase="recording", amplitude=0.15))
        ducker.duck()
        try:
            audio = record_while(pressed, on_chunk=_make_live_amplitude_pusher(voice_queue))
            overlay.show("transcribing")
            duration = len(audio) / config.SAMPLE_RATE
            if len(audio) >= config.SAMPLE_RATE // 2:
                amplitude = compute_amplitude(audio)
                text = stt.transcribe(audio, config.SAMPLE_RATE)
                if text:
                    phase = route_utterance(
                        text, voice_session, type_text,
                        assistant=assistant,
                        agent_phrase_matcher=agent_phrase_matcher,
                        kiris_dispatch=kiris_dispatch,
                    )
                    print(f"[Voice] {kind}: {text!r} ({duration:.1f}s, amp={amplitude:.4f}) -> phase={phase}")
                else:
                    print(f"[Voice] {kind}: empty transcription ({duration:.1f}s, amp={amplitude:.4f})")
            else:
                print(f"[Voice] {kind}: audio too short ({duration:.2f}s), ignored")
        except Exception as exc:  # noqa: BLE001 - one bad utterance must not kill the listener
            print(f"[Voice] {exc!r} (ignoring this utterance, voice loop keeps running)")
        finally:
            ducker.restore()
            overlay.hide()

        voice_queue.put(VoiceEvent(phase=phase, amplitude=amplitude))


def run_always_on(make_voice_session, voice_queue=None) -> None:
    """Runs on a background daemon thread: VadCapture blocks synchronously
    on the mic stream, so it can't share the asyncio event loop uvicorn
    uses. Heavy ML imports are deferred here so importing laris.daemon
    doesn't require torch/mlx_whisper to be installed."""
    from laris.audio_capture import VadCapture
    from laris.platform import get_backend

    if voice_queue is None:
        import queue
        voice_queue = queue.Queue()

    backend = get_backend()
    backend.warm()
    stt = backend
    voice_session = make_voice_session()

    for audio, sample_rate in VadCapture().stream_utterances():
        try:
            text = stt.transcribe(audio, sample_rate)
            if not text:
                continue
            phase = voice_session.handle_utterance(text)
            amplitude = compute_amplitude(audio)
            print(f"[Voice] heard: {text!r} -> phase={phase}")
        except Exception as exc:  # noqa: BLE001 - one bad utterance must not kill the listener
            print(f"[Voice] {exc!r} (ignoring this utterance, voice loop keeps running)")
            continue

        voice_queue.put(VoiceEvent(phase=phase, amplitude=amplitude))
