"""LARIS's standalone HTTP surface for the desktop overlay orb: /overlay
serves the orb page, /ws/voice streams VoiceEvent to it. Built as a factory
(build_app) so each daemon run gets its own token and its own event queue -
no module-level globals, unlike the panel's server.py (which only ever runs
one instance per process)."""
from __future__ import annotations

import asyncio
import queue as thread_queue
import sys
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from laris import auth as laris_auth
from laris.events import VoiceEvent
from laris import orb_theme
from laris.orb_state import OrbStateManager
from laris.runtime_mode import ModeState, ModeValidationError

def _frontend_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent)) / "frontend"


FRONTEND_DIR = _frontend_dir()

# Teto do long-poll de /overlay/state (SDD-C0 §14). O cliente deve usar um
# timeout global de HTTP maior que isto, senão mata a conexão antes da resposta.
MAX_WAIT_S = 25.0


def get_voice_event_queue(app: FastAPI) -> "thread_queue.Queue[VoiceEvent]":
    return app.state.voice_events


def build_app(token: str, voice_queue: "thread_queue.Queue[VoiceEvent] | None" = None, orb_state: OrbStateManager | None = None, mode_state: ModeState | None = None) -> FastAPI:
    """voice_queue: pass the SAME queue instance the PTT daemon loop pushes
    into so this app's /ws/voice actually streams live events instead of an
    unconnected queue nobody writes to. Defaults to a fresh, disconnected
    queue for standalone testing.
    orb_state: pass the SAME OrbStateManager instance the daemon uses so
    /overlay/state reflects live visibility/readiness changes. Defaults to
    a fresh, disconnected manager for standalone testing.
    mode_state: pass the SAME ModeState the daemon loop reads, so the tray's
    hands-free toggle applies without restarting the engine."""
    app = FastAPI()
    app.state.token = token
    app.state.voice_events = voice_queue if voice_queue is not None else thread_queue.Queue()
    app.state.orb_state = orb_state if orb_state is not None else OrbStateManager()
    app.state.mode_state = mode_state if mode_state is not None else ModeState()
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/overlay")
    def overlay_page():
        return FileResponse(FRONTEND_DIR / "overlay.html")

    @app.get("/theme")
    def get_theme(token: str | None = None, screen_w: float | None = None, screen_h: float | None = None):
        if not laris_auth.token_valid(token, app.state.token):
            raise HTTPException(status_code=403, detail="invalid token")
        theme = orb_theme.load_theme()
        response = {"theme": theme, "palettes": orb_theme.PALETTES}
        # Add rect only if both screen_w and screen_h are valid and positive
        if screen_w is not None and screen_h is not None and screen_w > 0 and screen_h > 0:
            x, y, w, h = orb_theme.position_rect_topleft(theme, screen_w, screen_h)
            response["rect"] = {"x": x, "y": y, "w": w, "h": h}
        return response

    @app.get("/overlay/state")
    async def get_overlay_state(token: str | None = None, since: int = 0, wait: float = 0.0):
        if not laris_auth.token_valid(token, app.state.token):
            raise HTTPException(status_code=403, detail="invalid token")
        # Clamp wait to [0, MAX_WAIT_S] (SDD-C0 §14)
        wait = max(0.0, min(MAX_WAIT_S, wait))
        orb_state = app.state.orb_state
        # Blocking wait must happen in a thread pool to avoid blocking the event loop
        snapshot = await asyncio.to_thread(orb_state.wait_for_change, since, wait)
        return {
            "visible": snapshot.visible,
            "ready": snapshot.ready,
            "mode": snapshot.mode,
            "serial": snapshot.serial,
            "status": snapshot.status,
            "progress": snapshot.progress,
        }

    @app.post("/theme")
    def post_theme(updates: dict, token: str | None = None):
        if not laris_auth.token_valid(token, app.state.token):
            raise HTTPException(status_code=403, detail="invalid token")
        try:
            theme = orb_theme.save_theme(updates)
        except orb_theme.ThemeValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"theme": theme, "palettes": orb_theme.PALETTES}

    @app.get("/mode")
    def get_mode(token: str | None = None):
        if not laris_auth.token_valid(token, app.state.token):
            raise HTTPException(status_code=403, detail="invalid token")
        return {"mode": app.state.mode_state.mode}

    @app.post("/mode")
    def post_mode(updates: dict, token: str | None = None):
        """Applies ASSISTANT_MODE to the running loop. The tray owns the
        persisted file (laris-settings.json); this only moves the live flag, so
        there is never a second writer racing it."""
        if not laris_auth.token_valid(token, app.state.token):
            raise HTTPException(status_code=403, detail="invalid token")
        try:
            mode = app.state.mode_state.set(updates.get("mode"))
        except ModeValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"mode": mode}

    @app.websocket("/ws/voice")
    async def ws_voice(websocket: WebSocket, token: str | None = None):
        # Recusar ANTES do accept. Aceitando primeiro, um token invalido ainda
        # dispara onopen no cliente, que o trata como conexao boa e zera o
        # backoff - o resultado era um cliente com token velho reconectando em
        # loop apertado. 1008 = policy violation.
        if not laris_auth.token_valid(token, websocket.app.state.token):
            await websocket.close(code=1008, reason="invalid or missing session token")
            return
        await websocket.accept()

        voice_queue = get_voice_event_queue(websocket.app)
        try:
            while True:
                try:
                    event = await asyncio.to_thread(voice_queue.get, timeout=0.5)
                except thread_queue.Empty:
                    continue
                await websocket.send_json(asdict(event))
        except WebSocketDisconnect:
            return

    return app
