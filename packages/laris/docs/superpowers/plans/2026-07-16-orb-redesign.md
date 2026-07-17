# Orb Redesign (Theme Engine + Archetypes) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded wireframe orb with a theme engine - 3 archetypes (Waveform default, Reactor, Faceted) x 4 palettes (Blade default) - plus configurable position/size persisted in `~/.config/voice-at/orb-theme.json` and a `GET/POST /theme` API.

**Architecture:** Python side: `laris/orb_theme.py` owns config load/save/validation and the pure `position_rect` math; `server.py` gains `/theme` endpoints; `overlay_app.py` reads position/size at boot and polls the file mtime to reposition live. Frontend: `voice-orb.js` becomes the engine (voice ballistics, glitch scheduler, demo mode, theme registry); each archetype is one file in `frontend/themes/` registering `window.ORB_THEMES[name]`.

**Tech Stack:** Python 3.11 / FastAPI / pytest (existing laris suite); vanilla JS + 2D canvas (Waveform, Reactor) + three.js r160 already vendored (Faceted only).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-16-orb-redesign-design.md`. Defaults verbatim: archetype `waveform`, palette `blade`, position `center`, size `190`.
- Palettes `{accent, hot}`: blade `#3fb6c4/#d8f4f7`, noir `#c94f92/#f7d8ea`, acid `#79c94f/#e9f7d8`, ember `#cf9b3a/#f7ecd8`.
- Motion rules: mesh deformation FORBIDDEN; mechanical motion only; keep VU ballistics (attack 0.55 / release 0.10), activation pulse (decay 0.88), idle frame-skip (1 of 8 frames when settled).
- Transparent-canvas constraint (WKWebView): no opaque clears, no translucent full-canvas fills; afterglow = stored ghost snapshots only.
- Approved visual reference files (committed by Task 1): `docs/superpowers/mockups/waveform-approved.html` (look), sizes/brightness from the v3 desktop preview: 190px, idle dim 0.75.
- Deviation from spec (both simplifications, keep them): theme reaches the page by polling `GET /theme` every 3s (not a ws push); overlay_app repositions by polling the config file mtime every 2s (not a stdin command).
- Code and comments in English; UI strings pt-BR. Plain hyphen "-" only, never em/en dashes.
- The existing `/ws/voice` contract (`{amplitude, phase}` VoiceEvent dicts) and element ids `phaseCaption`/`ampFill` must keep working - the claude-code-ops dashboard reuses them.
- All Python verification with `.venv/bin/python -m pytest` from `/Users/samdev/code/laris`. Suite baseline: 125 passed.

---

### Task 1: orb_theme.py - config, validation, position math

**Files:**
- Create: `laris/orb_theme.py`
- Create: `docs/superpowers/mockups/waveform-approved.html` (copy of `.superpowers/brainstorm/75670-1784247156/content/orb-desktop-live-v3.html`)
- Modify: `laris/config.py` (append one constant)
- Test: `tests/test_orb_theme.py`

**Interfaces:**
- Produces: `ARCHETYPES = ("waveform", "reactor", "faceted")`; `PALETTES: dict[str, dict[str, str]]` (keys blade/noir/acid/ember, values `{"accent": hex, "hot": hex}`); `DEFAULTS: dict`; `load_theme(path: Path | None = None) -> dict` (missing/corrupt -> DEFAULTS written to disk); `save_theme(updates: dict, path: Path | None = None) -> dict` (validates, merges, persists, returns full dict; raises `ThemeValidationError` listing valid options); `position_rect(theme: dict, screen_w: float, screen_h: float) -> tuple[float, float]` (bottom-left origin, macOS convention); `laris.config.ORB_THEME_PATH`.

- [ ] **Step 1: Copy the approved mockup into docs (versioned reference)**

```bash
mkdir -p docs/superpowers/mockups
cp .superpowers/brainstorm/75670-1784247156/content/orb-desktop-live-v3.html docs/superpowers/mockups/waveform-approved.html
```

- [ ] **Step 2: Append to `laris/config.py`**

```python
ORB_THEME_PATH: str = os.environ.get(
    "ORB_THEME_PATH", "~/.config/voice-at/orb-theme.json"
)
```

- [ ] **Step 3: Write the failing tests**

`tests/test_orb_theme.py`:
```python
import json
from pathlib import Path

import pytest

from laris import orb_theme


def test_load_missing_file_writes_defaults(tmp_path):
    path = tmp_path / "orb-theme.json"
    theme = orb_theme.load_theme(path)
    assert theme == orb_theme.DEFAULTS
    assert json.loads(path.read_text()) == orb_theme.DEFAULTS


def test_load_corrupt_file_rewrites_defaults(tmp_path):
    path = tmp_path / "orb-theme.json"
    path.write_text("{not json")
    assert orb_theme.load_theme(path) == orb_theme.DEFAULTS


def test_save_merges_and_persists(tmp_path):
    path = tmp_path / "orb-theme.json"
    theme = orb_theme.save_theme({"palette": "ember"}, path)
    assert theme["palette"] == "ember"
    assert theme["archetype"] == "waveform"  # untouched defaults survive
    assert json.loads(path.read_text())["palette"] == "ember"


@pytest.mark.parametrize("bad", [
    {"archetype": "sphere"},
    {"palette": "rainbow"},
    {"position": "left"},
    {"size": "big"},
    {"size": 20},
    {"custom": [1]},
])
def test_save_rejects_invalid(bad, tmp_path):
    with pytest.raises(orb_theme.ThemeValidationError):
        orb_theme.save_theme(bad, tmp_path / "orb-theme.json")


def test_position_rect_all_presets():
    theme = dict(orb_theme.DEFAULTS, size=100)
    w, h = 1000.0, 800.0
    cases = {
        "top-left": (16.0, 800 - 100 - 40.0),
        "top-center": (450.0, 800 - 100 - 40.0),
        "top-right": (1000 - 100 - 16.0, 800 - 100 - 40.0),
        "bottom-left": (16.0, 16.0),
        "bottom-right": (1000 - 100 - 16.0, 16.0),
        "center": (450.0, 350.0),
    }
    for preset, expected in cases.items():
        theme["position"] = preset
        assert orb_theme.position_rect(theme, w, h) == expected


def test_position_rect_custom_coordinates():
    theme = dict(orb_theme.DEFAULTS, position="custom", custom=[123, 456])
    assert orb_theme.position_rect(theme, 2000.0, 1200.0) == (123.0, 456.0)
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_orb_theme.py -v`
Expected: FAIL (ModuleNotFoundError: laris.orb_theme).

- [ ] **Step 5: Implement `laris/orb_theme.py`**

```python
"""Orb theme config: archetype x palette x position, persisted as JSON.
Single source of truth for the /theme endpoint, overlay_app and the menu bar."""
import json
from pathlib import Path

from laris import config

ARCHETYPES = ("waveform", "reactor", "faceted")
PALETTES = {
    "blade": {"accent": "#3fb6c4", "hot": "#d8f4f7"},
    "noir": {"accent": "#c94f92", "hot": "#f7d8ea"},
    "acid": {"accent": "#79c94f", "hot": "#e9f7d8"},
    "ember": {"accent": "#cf9b3a", "hot": "#f7ecd8"},
}
POSITIONS = ("top-left", "top-center", "top-right",
             "bottom-left", "bottom-right", "center", "custom")
SIZE_RANGE = (80, 400)
_TOP_MARGIN = 40.0
_EDGE_MARGIN = 16.0

DEFAULTS = {
    "archetype": "waveform",
    "palette": "blade",
    "position": "center",
    "custom": [0, 0],
    "size": 190,
}


class ThemeValidationError(ValueError):
    pass


def _theme_path(path: Path | None) -> Path:
    return path or Path(config.ORB_THEME_PATH).expanduser()


def _validate(theme: dict) -> None:
    if theme["archetype"] not in ARCHETYPES:
        raise ThemeValidationError(f"archetype must be one of {ARCHETYPES}")
    if theme["palette"] not in PALETTES:
        raise ThemeValidationError(f"palette must be one of {tuple(PALETTES)}")
    if theme["position"] not in POSITIONS:
        raise ThemeValidationError(f"position must be one of {POSITIONS}")
    size = theme["size"]
    if not isinstance(size, int) or not SIZE_RANGE[0] <= size <= SIZE_RANGE[1]:
        raise ThemeValidationError(f"size must be an int in {SIZE_RANGE}")
    custom = theme["custom"]
    if (not isinstance(custom, list) or len(custom) != 2
            or not all(isinstance(v, (int, float)) for v in custom)):
        raise ThemeValidationError("custom must be [x, y]")


def load_theme(path: Path | None = None) -> dict:
    """Read the theme; missing or corrupt file resets to DEFAULTS on disk."""
    path = _theme_path(path)
    try:
        theme = {**DEFAULTS, **json.loads(path.read_text(encoding="utf-8"))}
        _validate(theme)
        return theme
    except (OSError, ValueError):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULTS, indent=2), encoding="utf-8")
        return dict(DEFAULTS)


def save_theme(updates: dict, path: Path | None = None) -> dict:
    """Merge updates over the stored theme, validate, persist, return it."""
    path = _theme_path(path)
    theme = {**load_theme(path), **updates}
    _validate(theme)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(theme, indent=2), encoding="utf-8")
    return theme


def position_rect(theme: dict, screen_w: float, screen_h: float) -> tuple[float, float]:
    """Bottom-left origin (macOS AppKit convention) for the panel corner."""
    size = float(theme["size"])
    pos = theme["position"]
    if pos == "custom":
        return float(theme["custom"][0]), float(theme["custom"][1])
    x = {
        "left": _EDGE_MARGIN,
        "center": (screen_w - size) / 2,
        "right": screen_w - size - _EDGE_MARGIN,
    }["left" if pos.endswith("left") else "right" if pos.endswith("right") else "center"]
    if pos.startswith("top"):
        y = screen_h - size - _TOP_MARGIN
    elif pos.startswith("bottom"):
        y = _EDGE_MARGIN
    else:  # center
        y = (screen_h - size) / 2
    return x, y
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_orb_theme.py -v`
Expected: 10 PASS. Then full suite: `.venv/bin/python -m pytest -q` -> 135 passed.

- [ ] **Step 7: Commit**

```bash
git add laris/orb_theme.py laris/config.py tests/test_orb_theme.py docs/superpowers/mockups/
git commit -m "feat: orb theme config with validation and position math"
```

---

### Task 2: /theme endpoints on the overlay server

**Files:**
- Modify: `laris/server.py` (add two routes inside `build_app`)
- Test: `tests/test_theme_endpoint.py`

**Interfaces:**
- Consumes: `laris.orb_theme.load_theme/save_theme/ThemeValidationError`, existing `laris.auth.token_valid`.
- Produces: `GET /theme?token=` -> full theme dict + `{"palettes": PALETTES}` merged as `{"theme": {...}, "palettes": {...}}`; `POST /theme?token=` body = partial updates -> same shape; 403 on bad token; 422 with valid options on bad values.

- [ ] **Step 1: Write the failing tests**

`tests/test_theme_endpoint.py`:
```python
from fastapi.testclient import TestClient

from laris.server import build_app


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("ORB_THEME_PATH", str(tmp_path / "orb-theme.json"))
    # config reads env at import time for this constant - reload pattern:
    import importlib

    from laris import config as laris_config
    importlib.reload(laris_config)
    app = build_app(token="tok")
    return TestClient(app)


def test_get_theme_returns_defaults_and_palettes(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.get("/theme", params={"token": "tok"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["theme"]["archetype"] == "waveform"
    assert body["palettes"]["blade"]["accent"] == "#3fb6c4"


def test_get_theme_rejects_bad_token(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    assert client.get("/theme", params={"token": "nope"}).status_code == 403


def test_post_theme_persists_and_returns(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/theme", params={"token": "tok"}, json={"palette": "acid"})
    assert resp.status_code == 200
    assert resp.json()["theme"]["palette"] == "acid"
    assert client.get("/theme", params={"token": "tok"}).json()["theme"]["palette"] == "acid"


def test_post_theme_invalid_value_is_422_with_options(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/theme", params={"token": "tok"}, json={"archetype": "cube"})
    assert resp.status_code == 422
    assert "waveform" in resp.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_theme_endpoint.py -v`
Expected: FAIL (404 on /theme).

- [ ] **Step 3: Add routes to `laris/server.py` inside `build_app`, after the `/overlay` route**

```python
    @app.get("/theme")
    def get_theme(token: str | None = None):
        if not laris_auth.token_valid(token, app.state.token):
            raise HTTPException(status_code=403, detail="invalid token")
        return {"theme": orb_theme.load_theme(), "palettes": orb_theme.PALETTES}

    @app.post("/theme")
    def post_theme(updates: dict, token: str | None = None):
        if not laris_auth.token_valid(token, app.state.token):
            raise HTTPException(status_code=403, detail="invalid token")
        try:
            theme = orb_theme.save_theme(updates)
        except orb_theme.ThemeValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"theme": theme, "palettes": orb_theme.PALETTES}
```

Imports to add at the top of server.py: `from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect` (HTTPException is new) and `from laris import orb_theme`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_theme_endpoint.py -v` -> 4 PASS.
Full suite: `.venv/bin/python -m pytest -q` -> 139 passed.

- [ ] **Step 5: Commit**

```bash
git add laris/server.py tests/test_theme_endpoint.py
git commit -m "feat: GET/POST /theme endpoints on the overlay server"
```

---

### Task 3: frontend engine + Waveform archetype

**Files:**
- Create: `frontend/themes/waveform.js`
- Rewrite: `frontend/voice-orb.js`
- Modify: `frontend/overlay.html` (script tags + canvas wrap)

**Interfaces:**
- Consumes: `GET /theme?token=` (Task 2), `/ws/voice` events `{amplitude, phase}`.
- Produces: theme module contract used by Task 4 - each file in `frontend/themes/` does:
  `window.ORB_THEMES = window.ORB_THEMES || {};`
  `window.ORB_THEMES.<name> = function create(wrap, size) { return { draw(state, palette) {}, dispose() {} } }`
  where `state = { t, active, v, glitch, phase }` (t seconds, v 0..1 smoothed energy incl. pulse, glitch boolean) and `palette = { accent, hot }`.
  Engine globals themes may use: `window.ORB_UTIL = { rgba(hex, alpha) }`.

- [ ] **Step 1: Write `frontend/themes/waveform.js`**

Port of the approved mockup (`docs/superpowers/mockups/waveform-approved.html`), parameterized by size and palette. Complete file:

```javascript
// Waveform archetype - circular spectrum analyzer (approved 2026-07-16).
// Hot core, radial bars with ghost afterglow, dashed tech ring, thin outer
// ring, glitch displacement. No radar sweep (explicitly rejected).
(function () {
  window.ORB_THEMES = window.ORB_THEMES || {};

  window.ORB_THEMES.waveform = function create(wrap, size) {
    const canvas = document.createElement("canvas");
    canvas.width = size; canvas.height = size;
    wrap.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    const rgba = window.ORB_UTIL.rgba;

    const C = size / 2, S = size / 280;
    const N = size < 160 ? 40 : 56;
    const bands = new Array(N).fill(0);
    const ghosts = [new Array(N).fill(0), new Array(N).fill(0)];
    let ghostClock = 0;

    function draw(s, pal) {
      ctx.clearRect(0, 0, size, size);
      const dim = s.active ? 1 : 0.75;
      const R0 = 62 * S;
      const glitchShift = s.glitch ? (Math.random() - 0.5) * 4 * S : 0;

      const coreR = (6 + s.v * 4) * S;
      const g = ctx.createRadialGradient(C, C, 1, C, C, coreR * 3.2);
      g.addColorStop(0, rgba(pal.hot, 0.95 * dim + s.v * 0.05));
      g.addColorStop(0.4, rgba(pal.accent, 0.30 * dim + s.v * 0.25));
      g.addColorStop(1, rgba(pal.accent, 0));
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(C, C, coreR * 3.2, 0, 7); ctx.fill();

      ctx.setLineDash([3 * S, 5 * S]);
      ctx.beginPath(); ctx.arc(C, C, 46 * S + s.v * 3 * S, 0, 7);
      ctx.strokeStyle = rgba(pal.accent, 0.5 * dim); ctx.lineWidth = 1.3; ctx.stroke();
      ctx.setLineDash([]);

      ghostClock++;
      if (ghostClock % 5 === 0) { ghosts[1] = ghosts[0].slice(); ghosts[0] = bands.slice(); }

      for (let i = 0; i < N; i++) {
        const band = Math.abs(Math.sin(i * 0.55 + s.t * 3.1) * Math.sin(i * 0.13 + s.t * 1.7));
        const target = s.active ? s.v * band : 0.03 * Math.abs(Math.sin(i + s.t));
        bands[i] += (target - bands[i]) * (target > bands[i] ? 0.5 : 0.12);
        const ang = -Math.PI / 2 + (i / N) * Math.PI * 2;
        const cos = Math.cos(ang), sin = Math.sin(ang);
        for (let layer = 1; layer >= 0; layer--) {
          const val = layer === 0 ? bands[i] : ghosts[layer][i];
          if (layer > 0 && val < 0.02) continue;
          const h = (4 + val * 46) * S;
          ctx.beginPath();
          ctx.moveTo(C + cos * R0 + (layer ? 0 : glitchShift), C + sin * R0);
          ctx.lineTo(C + cos * (R0 + h) + (layer ? 0 : glitchShift), C + sin * (R0 + h));
          ctx.strokeStyle = layer === 0
            ? rgba(val > 0.55 ? pal.hot : pal.accent, (0.60 + val * 0.40) * dim)
            : rgba(pal.accent, 0.18 * dim);
          ctx.lineWidth = 3 * S * (size < 160 ? 1.35 : 1);
          ctx.stroke();
        }
      }

      ctx.beginPath(); ctx.arc(C, C, 124 * S, 0, 7);
      ctx.strokeStyle = rgba(pal.accent, 0.30 * dim + s.v * 0.25);
      ctx.lineWidth = 1.2; ctx.stroke();
      if (s.glitch) {
        const a0 = Math.random() * 7;
        ctx.beginPath(); ctx.arc(C + 3 * S, C, 124 * S, a0, a0 + 0.5);
        ctx.strokeStyle = rgba(pal.hot, 0.7); ctx.lineWidth = 1.4; ctx.stroke();
      }
    }

    return { draw, dispose() { canvas.remove(); } };
  };
})();
```

- [ ] **Step 2: Rewrite `frontend/voice-orb.js` as the engine**

Complete file:

```javascript
// Orb engine: voice ballistics + glitch scheduler + theme registry.
// Themes live in /static/themes/*.js and register window.ORB_THEMES[name].
// ?demo=1 replaces the websocket with a fake idle/speaking cycle.
(function () {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token");
  const demo = params.get("demo") === "1";
  if (!token && !demo) return;

  window.ORB_UTIL = {
    rgba(hex, a) {
      const r = parseInt(hex.slice(1, 3), 16), g = parseInt(hex.slice(3, 5), 16),
            b = parseInt(hex.slice(5, 7), 16);
      return `rgba(${r},${g},${b},${a})`;
    },
  };

  const wrap = document.getElementById("orb-canvas-wrap");
  const caption = document.getElementById("phaseCaption");
  const ampFill = document.getElementById("ampFill");
  const fallback = document.getElementById("orb-fallback");

  const PHASE_CAPTIONS = {
    recording: "ouvindo...",
    awaiting_project: "qual projeto?",
    awaiting_dictation: "pode ditar a mensagem...",
    awaiting_send: 'digitado - diga "manda" ou aperte enter',
  };

  let theme = { archetype: "waveform", palette: "blade", size: 190 };
  let palettes = { blade: { accent: "#3fb6c4", hot: "#d8f4f7" } };
  let instance = null;

  function mountTheme() {
    if (instance) instance.dispose();
    wrap.innerHTML = "";
    const size = wrap.clientWidth || theme.size;
    const factory = window.ORB_THEMES[theme.archetype] || window.ORB_THEMES.waveform;
    instance = factory(wrap, size);
    if (fallback) fallback.classList.add("hide");
  }

  async function fetchTheme() {
    if (demo) return;
    try {
      const resp = await fetch(`/theme?token=${encodeURIComponent(token)}`);
      if (!resp.ok) return;
      const body = await resp.json();
      palettes = body.palettes;
      const changed = body.theme.archetype !== theme.archetype;
      theme = body.theme;
      if (changed || !instance) mountTheme();
    } catch (e) { /* server restarting - keep current theme */ }
  }

  // --- voice state (ported ballistics: attack .55, release .10, pulse .88) ---
  let t = 0, targetEnergy = 0, smoothedVoice = 0, activationPulse = 0;
  let active = false, idleFrameSkip = 0;
  let glitchAt = 4 + Math.random() * 4, glitchLife = 0;

  function setPhase(phase) {
    const wasIdle = !active;
    active = phase !== "idle";
    if (wasIdle && active) activationPulse = 1.0;
    wrap.classList.toggle("active", active);
    const text = PHASE_CAPTIONS[phase];
    if (text) { caption.textContent = text; caption.classList.add("show"); }
    else caption.classList.remove("show");
  }

  function animate() {
    requestAnimationFrame(animate);
    if (!instance) return;
    const settled = !active && smoothedVoice < 0.01;
    if (settled) {
      idleFrameSkip = (idleFrameSkip + 1) % 8;
      if (idleFrameSkip !== 0) return;
    } else idleFrameSkip = 0;

    t += 0.014;
    if (activationPulse > 0.001) activationPulse *= 0.88; else activationPulse = 0;
    targetEnergy *= 0.96;
    const rate = targetEnergy > smoothedVoice ? 0.55 : 0.10;
    smoothedVoice += (targetEnergy - smoothedVoice) * rate;
    const v = Math.min(1, smoothedVoice * 0.95 + activationPulse * 0.5 + (active ? 0.12 : 0));
    if (ampFill) ampFill.style.width = Math.min(100, v * 100) + "%";

    glitchAt -= 1 / 60;
    if (glitchAt <= 0) { glitchLife = 0.12; glitchAt = 4 + Math.random() * 4; }
    if (glitchLife > 0) glitchLife -= 1 / 60;

    instance.draw(
      { t, active, v, glitch: glitchLife > 0, phase: null },
      palettes[theme.palette] || palettes.blade
    );
  }

  function connectVoice() {
    if (demo) {
      setInterval(() => {
        const on = (Math.floor(Date.now() / 7000) % 2) === 1;
        setPhase(on ? "recording" : "idle");
        if (on) {
          const phrase = (Math.sin(Date.now() / 1100) + 1) / 2;
          targetEnergy = phrase < 0.22 ? 0.02
            : 0.18 + Math.max(0, Math.sin(Date.now() / 190) * 0.5) * 0.6;
        }
      }, 100);
      return;
    }
    const ws = new WebSocket(`ws://${window.location.host}/ws/voice?token=${encodeURIComponent(token)}`);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.error) return;
      targetEnergy = data.amplitude;
      setPhase(data.phase);
    };
    ws.onclose = () => setPhase("idle");
  }

  fetchTheme().then(() => { if (!instance) mountTheme(); });
  setInterval(fetchTheme, 3000);
  connectVoice();
  animate();
  setPhase("idle");
})();
```

- [ ] **Step 3: Update `frontend/overlay.html`**

Replace the two script tags at the bottom with:
```html
<script src="/static/vendor/three.min.js"></script>
<script src="/static/themes/waveform.js"></script>
<script src="/static/themes/reactor.js"></script>
<script src="/static/themes/faceted.js"></script>
<script src="/static/voice-orb.js"></script>
```
(reactor.js/faceted.js 404 harmlessly until Task 4 lands; if the executor prefers, add them in Task 4 instead.)
Also update the size CSS block: `#orb-canvas-wrap, #orb-canvas-wrap.active { width: 100vw; height: 100vh; ... }` so the panel size (driven by orb-theme.json) defines the canvas size.

- [ ] **Step 4: Visual smoke (demo mode, plain browser)**

Run: `cd /Users/samdev/code/laris && .venv/bin/python -c "
import uvicorn
from laris.server import build_app
uvicorn.run(build_app(token='dev'), host='127.0.0.1', port=8433)
" &` then open `http://127.0.0.1:8433/overlay?demo=1`.
Expected: Waveform orb in Blade, cycling idle -> speaking every 7s, glitch tic every 4-8s, no radar. Kill the server after.

- [ ] **Step 5: Run full pytest suite (guard against server.py import breakage)**

Run: `.venv/bin/python -m pytest -q` -> 139 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/themes/waveform.js frontend/voice-orb.js frontend/overlay.html
git commit -m "feat: orb theme engine with Waveform archetype (approved design)"
```

---

### Task 4: Reactor and Faceted archetypes

**Files:**
- Create: `frontend/themes/reactor.js`
- Create: `frontend/themes/faceted.js`

**Interfaces:**
- Consumes: theme module contract from Task 3 (`create(wrap, size) -> {draw(state, palette), dispose()}`, `window.ORB_UTIL.rgba`, global `THREE` from vendored three.min.js).
- Produces: `window.ORB_THEMES.reactor`, `window.ORB_THEMES.faceted`.

- [ ] **Step 1: Write `frontend/themes/reactor.js`**

```javascript
// Reactor archetype - concentric HUD arcs (screen-2 candidate A).
// Sharp core, 48-tick radial gauge lit by voice, three mechanical sweeps,
// fixed outer ring with cardinal ticks. Brightness hierarchy only.
(function () {
  window.ORB_THEMES = window.ORB_THEMES || {};

  window.ORB_THEMES.reactor = function create(wrap, size) {
    const canvas = document.createElement("canvas");
    canvas.width = size; canvas.height = size;
    wrap.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    const rgba = window.ORB_UTIL.rgba;
    const C = size / 2, S = size / 300;

    function arc(pal, r, a0, a1, w, alpha) {
      ctx.beginPath(); ctx.arc(C, C, r * S, a0, a1);
      ctx.strokeStyle = rgba(pal.accent, alpha); ctx.lineWidth = w; ctx.stroke();
    }

    function draw(s, pal) {
      ctx.clearRect(0, 0, size, size);
      const dim = s.active ? 1 : 0.6;

      const coreR = (16 + s.v * 7) * S;
      const g = ctx.createRadialGradient(C, C, 2, C, C, coreR * 2.2);
      g.addColorStop(0, rgba(pal.hot, 0.75 * dim + s.v * 0.25));
      g.addColorStop(0.35, rgba(pal.accent, 0.35 * dim + s.v * 0.3));
      g.addColorStop(1, rgba(pal.accent, 0));
      ctx.fillStyle = g;
      ctx.beginPath(); ctx.arc(C, C, coreR * 2.2, 0, 7); ctx.fill();

      const lit = Math.round(48 * Math.min(1, s.v * 1.4));
      for (let i = 0; i < 48; i++) {
        const ang = -Math.PI / 2 + (i / 48) * Math.PI * 2;
        const on = s.active && i < lit;
        ctx.beginPath();
        ctx.moveTo(C + Math.cos(ang) * 46 * S, C + Math.sin(ang) * 46 * S);
        ctx.lineTo(C + Math.cos(ang) * (on ? 58 : 52) * S, C + Math.sin(ang) * (on ? 58 : 52) * S);
        ctx.strokeStyle = rgba(pal.accent, on ? 0.95 : 0.18 * dim);
        ctx.lineWidth = on ? 2.2 : 1; ctx.stroke();
      }

      const sweeps = [
        { r: 76, len: 1.1 + s.v * 1.2, speed: 0.9, w: 3, a: 0.7 },
        { r: 88, len: 0.5 + s.v * 0.8, speed: -1.4, w: 2, a: 0.5 },
        { r: 97, len: 1.9, speed: 0.35, w: 1.2, a: 0.32 },
      ];
      for (const sw of sweeps) {
        const base = s.t * sw.speed;
        arc(pal, sw.r, base, base + sw.len, sw.w, sw.a * dim + s.v * 0.2);
      }

      arc(pal, 112, 0, 7, 1, 0.22 * dim);
      for (let i = 0; i < 8; i++) {
        const ang = (i / 8) * Math.PI * 2 + Math.PI / 8;
        ctx.beginPath();
        ctx.moveTo(C + Math.cos(ang) * 108 * S, C + Math.sin(ang) * 108 * S);
        ctx.lineTo(C + Math.cos(ang) * 117 * S, C + Math.sin(ang) * 117 * S);
        ctx.strokeStyle = rgba(pal.accent, 0.4 * dim + s.v * 0.3);
        ctx.lineWidth = 1.6; ctx.stroke();
      }
    }

    return { draw, dispose() { canvas.remove(); } };
  };
})();
```

- [ ] **Step 2: Write `frontend/themes/faceted.js`**

```javascript
// Faceted archetype - rigid lit plates (screen-2 candidate C), three.js.
// Plates light in waves + voice-driven flashes; geometry NEVER deforms.
// Falls back to Waveform if THREE is unavailable (spec error-handling rule).
(function () {
  window.ORB_THEMES = window.ORB_THEMES || {};

  window.ORB_THEMES.faceted = function create(wrap, size) {
    if (typeof THREE === "undefined") {
      return window.ORB_THEMES.waveform(wrap, size);
    }
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100);
    camera.position.z = 6.2;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(size, size);
    wrap.appendChild(renderer.domElement);

    const geo = new THREE.IcosahedronGeometry(1.7, 1).toNonIndexed();
    const faceCount = geo.attributes.position.count / 3;
    const colors = new Float32Array(geo.attributes.position.count * 3);
    geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true }));
    scene.add(mesh);

    const edgeMat = new THREE.LineBasicMaterial({ transparent: true, opacity: 0.5 });
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 1), edgeMat);
    edges.scale.setScalar(1.002);
    scene.add(edges);

    const ringMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.3 });
    const ring = new THREE.Mesh(new THREE.TorusGeometry(2.35, 0.006, 4, 96), ringMat);
    ring.rotation.x = Math.PI / 2 - 0.28;
    scene.add(ring);

    const flicker = new Array(faceCount).fill(0);

    function draw(s, pal) {
      const ACC = new THREE.Color(pal.accent);
      edgeMat.color.copy(ACC); ringMat.color.copy(ACC);
      const dim = s.active ? 1 : 0.5;
      for (let f = 0; f < faceCount; f++) {
        const wave = Math.sin(f * 0.7 + s.t * 2.2) * 0.5 + 0.5;
        const flash = s.active && Math.random() < s.v * 0.05 ? 1 : 0;
        flicker[f] = Math.max(flicker[f] * 0.93, flash);
        const level = (0.06 + wave * 0.10) * dim + s.v * wave * 0.45 + flicker[f] * 0.8;
        const c = ACC.clone().multiplyScalar(Math.min(1.2, 0.12 + level));
        for (let vtx = 0; vtx < 3; vtx++) {
          const i = (f * 3 + vtx) * 3;
          colors[i] = c.r; colors[i + 1] = c.g; colors[i + 2] = c.b;
        }
      }
      geo.attributes.color.needsUpdate = true;
      mesh.rotation.y += 0.004 + s.v * 0.012;
      edges.rotation.copy(mesh.rotation);
      ring.rotation.z = s.t * 0.25;
      ringMat.opacity = 0.12 * dim + s.v * 0.35;
      edgeMat.opacity = 0.35 * dim + s.v * 0.4;
      renderer.render(scene, camera);
    }

    return {
      draw,
      dispose() { renderer.dispose(); renderer.domElement.remove(); },
    };
  };
})();
```

- [ ] **Step 3: Visual smoke of both**

Same dev server as Task 3 Step 4. Set each via the API and watch the page switch within 3s:
```bash
curl -X POST "http://127.0.0.1:8433/theme?token=dev" -H 'Content-Type: application/json' -d '{"archetype": "reactor"}'
curl -X POST "http://127.0.0.1:8433/theme?token=dev" -H 'Content-Type: application/json' -d '{"archetype": "faceted", "palette": "noir"}'
curl -X POST "http://127.0.0.1:8433/theme?token=dev" -H 'Content-Type: application/json' -d '{"archetype": "waveform", "palette": "blade"}'
```
Expected: page hot-swaps archetype/palette without reload. (Note: demo=1 skips fetchTheme, so run this smoke WITHOUT demo param but with the daemon idle - or temporarily allow fetch in demo. Simplest: open `/overlay?token=dev` - no voice events, orb sits in idle, theme swaps still visible.)

- [ ] **Step 4: Commit**

```bash
git add frontend/themes/reactor.js frontend/themes/faceted.js
git commit -m "feat: Reactor and Faceted orb archetypes"
```

---

### Task 5: overlay_app position/size + live reposition

**Files:**
- Modify: `laris/overlay_app.py`
- Test: `tests/test_overlay_position.py` (pure parts only)

**Interfaces:**
- Consumes: `laris.orb_theme.load_theme/position_rect`.
- Produces: panel rect from theme at boot; mtime poll (2s NSTimer) reapplies rect when orb-theme.json changes.

- [ ] **Step 1: Write the failing test**

`tests/test_overlay_position.py`:
```python
from laris import orb_theme
from laris.overlay_app import panel_rect_for_theme


def test_panel_rect_uses_theme_position_and_size():
    theme = dict(orb_theme.DEFAULTS, position="bottom-right", size=100)
    x, y, w, h = panel_rect_for_theme(theme, 1000.0, 800.0)
    assert (x, y, w, h) == (1000 - 100 - 16.0, 16.0, 100.0, 100.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_overlay_position.py -v`
Expected: FAIL (ImportError: panel_rect_for_theme). NOTE: importing laris.overlay_app must not require AppKit at module import time - keep `import AppKit` inside `main()` as it already is.

- [ ] **Step 3: Modify `laris/overlay_app.py`**

Add near the top (module level, no AppKit dependency):
```python
from laris import orb_theme


def panel_rect_for_theme(theme: dict, screen_w: float, screen_h: float):
    """(x, y, w, h) for the overlay panel - pure, testable."""
    x, y = orb_theme.position_rect(theme, screen_w, screen_h)
    size = float(theme["size"])
    return x, y, size, size
```

Inside `main()`, replace the `_SIZE`/`rect` block with:
```python
    theme = orb_theme.load_theme()
    screen = AppKit.NSScreen.mainScreen().frame()
    x, y, w, h = panel_rect_for_theme(theme, screen.size.width, screen.size.height)
    rect = AppKit.NSMakeRect(x, y, w, h)
```
Use `w`/`h` for the WKWebView frame too. After `web.loadRequest_(request)` add the mtime poll:
```python
    theme_path = orb_theme._theme_path(None)
    state = {"mtime": theme_path.stat().st_mtime if theme_path.exists() else 0}

    def _poll_theme() -> None:
        try:
            mtime = theme_path.stat().st_mtime
        except OSError:
            return
        if mtime == state["mtime"]:
            return
        state["mtime"] = mtime
        new_theme = orb_theme.load_theme()
        nx, ny, nw, nh = panel_rect_for_theme(
            new_theme, screen.size.width, screen.size.height)
        panel.setFrame_display_(AppKit.NSMakeRect(nx, ny, nw, nh), True)
        web.setFrame_(AppKit.NSMakeRect(0, 0, nw, nh))

    AppKit.NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
        2.0, True, lambda _timer: _poll_theme()
    )
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_overlay_position.py -v` -> 1 PASS.
Full suite: `.venv/bin/python -m pytest -q` -> 140 passed.

- [ ] **Step 5: Commit**

```bash
git add laris/overlay_app.py tests/test_overlay_position.py
git commit -m "feat: overlay panel position/size from orb theme, live reposition"
```

---

### Task 6: end-to-end validation + docs

**Files:**
- Modify: `README.md` (orb theming section)

- [ ] **Step 1: Live E2E with the real daemon (user at the machine)**

```bash
cd /Users/samdev/code/laris && .venv/bin/python -m laris
# hold cmd_r and dictate: orb appears CENTERED, 190px, Waveform/Blade,
# reacting to real voice; release: orb hides.
# then, from another terminal (token from ~/.config/voice-at/peers.json):
curl -X POST "http://127.0.0.1:8421/theme?token=$TOK" -d '{"position": "top-left", "archetype": "reactor"}' -H 'Content-Type: application/json'
# within ~3s the orb page swaps archetype; within ~2s the panel moves.
```
Expected: all of the above; CPU of the laris process while idle comparable to pre-redesign (frame-skip preserved).

- [ ] **Step 2: Update README.md**

Add under the existing feature description:
```markdown
## Orb themes

The desktop orb is themeable: 3 archetypes (waveform - default, reactor,
faceted) x 4 palettes (blade - default, noir, acid, ember), plus position
presets (center by default) and size. Config lives in
`~/.config/voice-at/orb-theme.json` and can be changed live:

```bash
curl -X POST "http://127.0.0.1:8421/theme?token=$TOK" \
     -H 'Content-Type: application/json' \
     -d '{"archetype": "waveform", "palette": "blade", "position": "center"}'
```

Visual dev/smoke without the daemon: open `/overlay?demo=1` on the overlay
server (fake voice cycle, no mic needed).
```

- [ ] **Step 3: Final commit**

```bash
git add README.md
git commit -m "docs: orb theming - archetypes, palettes, position API"
```
