from fastapi.testclient import TestClient


def test_frontend_dir_uses_pyinstaller_resource_dir(monkeypatch, tmp_path):
    import laris.server as server

    monkeypatch.setattr(server.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert server._frontend_dir() == tmp_path / "frontend"


def test_overlay_route_serves_html():
    from laris.server import build_app

    app = build_app(token="test-token")
    response = TestClient(app).get("/overlay")

    assert response.status_code == 200
    assert "voice-orb.js" in response.text


def test_ws_voice_rejects_missing_token():
    """A missing token is refused during the handshake, not after it. The old
    behaviour accepted the socket and sent an error frame, which the client
    read as a successful connection."""
    import pytest
    from starlette.websockets import WebSocketDisconnect

    from laris.server import build_app

    app = build_app(token="test-token")
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(app).websocket_connect("/ws/voice"):
            pass

    assert exc.value.code == 1008


def test_ws_voice_streams_queued_events():
    from laris.events import VoiceEvent
    from laris.server import build_app, get_voice_event_queue

    app = build_app(token="test-token")
    get_voice_event_queue(app).put(VoiceEvent(phase="recording", amplitude=0.5))

    with TestClient(app).websocket_connect("/ws/voice?token=test-token") as ws:
        data = ws.receive_json()
        assert data == {"phase": "recording", "amplitude": 0.5}


def test_a_closed_ws_does_not_eat_the_next_orb_event():
    """The orb only listens, so sending is the sole thing that notices it left -
    and while idle nothing is sent. A closed socket's handler outlived it, took
    the next event off the shared queue and died on the send, so the event never
    reached the reconnected orb. Needs a real server: TestClient cancels the
    handler task on exit, which hides the leak entirely."""
    import threading
    import time

    import uvicorn
    from websockets.sync.client import connect

    from laris.events import VoiceEvent
    from laris.server import build_app, get_voice_event_queue

    app = build_app(token="test-token")
    queue = get_voice_event_queue(app)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()
    try:
        while not server.started:
            time.sleep(0.05)
        port = server.servers[0].sockets[0].getsockname()[1]

        with connect(f"ws://127.0.0.1:{port}/ws/voice?token=test-token") as ws:
            queue.put(VoiceEvent(phase="recording", amplitude=0.5))
            ws.recv()
        time.sleep(1.0)  # let the handler notice the disconnect, as it would in life

        queue.put(VoiceEvent(phase="idle", amplitude=0.0))
        time.sleep(1.5)  # > the handler's 0.5s queue poll

        assert queue.qsize() == 1, "the closed socket's handler took the orb's next event"
    finally:
        server.should_exit = True


def test_theme_reports_ready_false_until_the_daemon_says_otherwise():
    from fastapi.testclient import TestClient
    from laris.server import build_app

    app = build_app(token="t")
    app.state.ready = False
    client = TestClient(app)

    assert client.get("/theme?token=t").json()["ready"] is False

    app.state.ready = True
    assert client.get("/theme?token=t").json()["ready"] is True


def test_theme_defaults_ready_to_true_when_unset():
    """An older daemon never sets the flag; treating that as "not ready"
    would leave the tray stuck on "Carregando modelo..." forever."""
    from fastapi.testclient import TestClient
    from laris.server import build_app

    client = TestClient(build_app(token="t"))

    assert client.get("/theme?token=t").json()["ready"] is True


def test_ws_rejects_a_bad_token_without_accepting_it():
    """Accepting first and closing after still fires onopen on the client, which
    reads it as a good connection and resets its reconnect backoff - a stale
    token then reconnects in a tight loop. Reject before the handshake so the
    client sees a failure and backs off. 1008 = policy violation."""
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    import pytest

    from laris.server import build_app

    client = TestClient(build_app(token="good"))

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/voice?token=wrong"):
            pass

    assert exc.value.code == 1008


def test_get_theme_without_screen_dimensions():
    """Verify that /theme without params returns the same shape as before."""
    from laris.server import build_app

    app = build_app(token="test-token")
    response = TestClient(app).get("/theme?token=test-token")

    assert response.status_code == 200
    data = response.json()
    assert "theme" in data
    assert "palettes" in data
    assert "rect" not in data  # No rect when dimensions omitted


def test_get_theme_with_valid_screen_dimensions(monkeypatch):
    """Verify that /theme with valid params adds rect in top-left coordinates.

    The theme is pinned here on purpose: load_theme() reads the developer's real
    ~/.config/voice-at/orb-theme.json, so without this the assertion below would
    depend on whatever position the machine running the tests happens to have
    selected in the tray."""
    from laris import orb_theme
    from laris.server import build_app

    monkeypatch.setattr(
        orb_theme, "load_theme",
        lambda *a, **k: {**orb_theme.DEFAULTS, "position": "center", "size": 190},
    )

    app = build_app(token="test-token")
    response = TestClient(app).get("/theme?token=test-token&screen_w=1920.0&screen_h=1080.0")

    assert response.status_code == 200
    data = response.json()
    assert "theme" in data
    assert "palettes" in data
    assert "rect" in data
    rect = data["rect"]
    assert "x" in rect and "y" in rect and "w" in rect and "h" in rect
    # Default theme: size=190, position=center → (865, 445, 190, 190)
    assert rect == {"x": 865.0, "y": 445.0, "w": 190.0, "h": 190.0}


def test_get_theme_with_zero_dimensions():
    """Verify that zero dimensions are treated as "not requested"."""
    from laris.server import build_app

    app = build_app(token="test-token")
    response = TestClient(app).get("/theme?token=test-token&screen_w=0.0&screen_h=1080.0")

    assert response.status_code == 200
    data = response.json()
    assert "rect" not in data


def test_get_theme_with_only_one_dimension():
    """Verify that providing only one dimension is treated as "not requested"."""
    from laris.server import build_app

    app = build_app(token="test-token")
    response = TestClient(app).get("/theme?token=test-token&screen_w=1920.0")

    assert response.status_code == 200
    data = response.json()
    assert "rect" not in data


def test_get_theme_invalid_token():
    """Verify that invalid token returns 403."""
    from laris.server import build_app

    app = build_app(token="test-token")
    response = TestClient(app).get("/theme?token=wrong-token")

    assert response.status_code == 403


def test_get_overlay_state_immediate_response():
    """Verify that /overlay/state?since=0 responds immediately."""
    from laris.server import build_app

    app = build_app(token="test-token")
    response = TestClient(app).get("/overlay/state?token=test-token&since=0")

    assert response.status_code == 200
    data = response.json()
    assert "visible" in data
    assert "ready" in data
    assert "mode" in data
    assert "serial" in data
    assert isinstance(data["visible"], bool)
    assert isinstance(data["ready"], bool)
    assert data["mode"] is None or isinstance(data["mode"], str)
    assert isinstance(data["serial"], int)
    assert data["serial"] >= 1


def test_get_overlay_state_invalid_token():
    """Verify that invalid token returns 403."""
    from laris.server import build_app

    app = build_app(token="test-token")
    response = TestClient(app).get("/overlay/state?token=wrong-token&since=0")

    assert response.status_code == 403


def test_get_overlay_state_with_injected_orb_state():
    """Verify that changes to injected orb_state are reflected in /overlay/state."""
    from laris.orb_state import OrbStateManager
    from laris.server import build_app

    orb_state = OrbStateManager()
    app = build_app(token="test-token", orb_state=orb_state)

    # Initial state
    response = TestClient(app).get("/overlay/state?token=test-token&since=0")
    data = response.json()
    assert data["visible"] is False
    assert data["ready"] is False

    # Mutate the state
    orb_state.show("dictate")
    response = TestClient(app).get("/overlay/state?token=test-token&since=0")
    data = response.json()
    assert data["visible"] is True
    assert data["mode"] == "dictate"

    # Hide it
    orb_state.hide()
    response = TestClient(app).get("/overlay/state?token=test-token&since=0")
    data = response.json()
    assert data["visible"] is False
    assert data["mode"] is None


def test_get_overlay_state_wait_clamped(monkeypatch):
    """Verify that an absurd wait is clamped to the server ceiling (SDD-C0 §14).

    MAX_WAIT_S is lowered here so the test proves the clamp without actually
    sleeping 25 seconds: with wait=999 the call must come back on the ceiling,
    not on the requested value."""
    import time

    from laris import server as server_mod

    monkeypatch.setattr(server_mod, "MAX_WAIT_S", 0.5)

    app = server_mod.build_app(token="test-token")
    start = time.monotonic()
    response = TestClient(app).get("/overlay/state?token=test-token&since=999&wait=999")
    elapsed = time.monotonic() - start

    assert response.status_code == 200
    assert elapsed < 3.0, f"wait nao foi limitado ao teto: levou {elapsed:.1f}s"


def test_post_mode_moves_the_shared_state_the_loop_reads():
    """The tray toggling hands-free must not need a daemon restart: the same
    ModeState instance the PTT loop reads has to change in place."""
    from laris.runtime_mode import ModeState
    from laris.server import build_app

    mode_state = ModeState("ptt")
    app = build_app(token="test-token", mode_state=mode_state)

    response = TestClient(app).post("/mode?token=test-token", json={"mode": "always_on"})

    assert response.status_code == 200
    assert response.json() == {"mode": "always_on"}
    assert mode_state.hands_free_allowed is True


def test_post_mode_rejects_an_unknown_mode():
    from laris.runtime_mode import ModeState
    from laris.server import build_app

    mode_state = ModeState("ptt")
    app = build_app(token="test-token", mode_state=mode_state)

    response = TestClient(app).post("/mode?token=test-token", json={"mode": "listen_always"})

    assert response.status_code == 422
    assert mode_state.mode == "ptt", "a rejected mode must not change anything"


def test_post_mode_requires_the_token():
    from laris.runtime_mode import ModeState
    from laris.server import build_app

    mode_state = ModeState("ptt")
    app = build_app(token="test-token", mode_state=mode_state)

    response = TestClient(app).post("/mode?token=errado", json={"mode": "always_on"})

    assert response.status_code == 403
    assert mode_state.mode == "ptt"


def test_get_mode_reports_the_live_value():
    from laris.runtime_mode import ModeState
    from laris.server import build_app

    app = build_app(token="test-token", mode_state=ModeState("always_on"))
    response = TestClient(app).get("/mode?token=test-token")
    assert response.json() == {"mode": "always_on"}
