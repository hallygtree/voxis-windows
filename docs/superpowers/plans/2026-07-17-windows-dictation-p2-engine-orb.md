# Windows Dictation P2 - Windows engine + Tauri orb window

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make dictation actually run on Windows: a `WindowsBackend` (faster-whisper STT + clipboard/Ctrl+V paste + no-op overlay/ducker), a platform-aware activation key default, and a Tauri-hosted transparent orb window. Packaging into a `.msi` is Plan 3.

**Architecture:** Builds on Plan 1's `laris/platform/` abstraction. `WindowsBackend` wires the existing `FasterWhisperTranscriber` to a new `dictation_windows.type_text` (pyperclip + pynput Ctrl+V). The orb overlay, which on macOS is a pyobjc window, becomes on Windows a transparent, always-on-top, click-through Tauri window pointing at the laris `/overlay` server the tray already knows the token for.

**Tech Stack:** Python 3.11 (pyperclip, pynput, faster-whisper), Rust/Tauri v2, vanilla TS. macOS path untouched.

## Global Constraints

- macOS path must not regress: the existing laris suite stays green (currently 162 fast tests); the Rust `cargo test` stays green (20 tests).
- All code/comments in English; UI copy pt-BR. Plain hyphen `-` only, never em/en dashes.
- Run pytest with `HF_HUB_DISABLE_XET=1`.
- The Windows dictation path is unit-tested with mocked pyperclip/pynput on macOS; real paste is verified on Windows in Plan 3's smoke.
- The Tauri orb window is gated to `#[cfg(windows)]` so the working macOS pyobjc overlay is untouched.
- `WindowsBackend` and `dictation_windows` must import pyperclip/pynput lazily (inside functions) so importing the module on any platform never fails or loads native libs eagerly.

## File Structure

```
laris/dictation_windows.py        # NEW - clipboard + Ctrl+V paste, default formatting
laris/platform/windows.py         # NEW - WindowsBackend (was referenced by get_backend since P1)
laris/config.py                   # MODIFY - platform-aware DICTATE_KEY default
laris/requirements.txt            # MODIFY - add pyperclip
tests/test_dictation_windows.py   # NEW
tests/test_windows_backend.py     # NEW
apps/tray/src-tauri/src/overlay.rs   # NEW - transparent orb window (Windows)
apps/tray/src-tauri/src/lib.rs       # MODIFY - open/close overlay with dictation state
```

## Parallelization

Two disjoint stacks, run concurrently by different executors:
- **Executor P (Python)**: Task 1 -> Task 2 (sequential; Task 2 imports Task 1's module). Files: `laris/dictation_windows.py`, `laris/platform/windows.py`, `laris/config.py`, `laris/requirements.txt`, `tests/test_dictation_windows.py`, `tests/test_windows_backend.py`.
- **Executor R (Rust)**: Task 3, independent. Files: `apps/tray/src-tauri/src/overlay.rs`, `apps/tray/src-tauri/src/lib.rs`.

No file is touched by both. The orchestrator validates each stack on the host (pytest for P, `cargo build`/`cargo test` for R), review-gates, and commits.

---

### Task 1: Windows dictation output (clipboard + Ctrl+V)

**Files:**
- Create: `laris/dictation_windows.py`
- Modify: `laris/requirements.txt` (add `pyperclip>=1.8`)
- Test: `tests/test_dictation_windows.py`

**Interfaces:**
- Produces: `laris.dictation_windows.type_text(text: str) -> None` - default-formats the text, saves the clipboard, copies the text, sends Ctrl+V, restores the clipboard best-effort. Also `format_for_focus(text: str) -> str` (default prose formatting, no app detection). Clipboard/keyboard actions go through patchable module-level seams `_set_clipboard`, `_get_clipboard`, `_paste_ctrl_v` so tests need neither pyperclip/pynput nor a real desktop.
- Consumes: nothing from other tasks.

- [ ] **Step 1: Write the failing test**

`tests/test_dictation_windows.py`:

```python
"""Windows dictation output - clipboard + Ctrl+V, with the OS seams mocked."""
import laris.dictation_windows as dw


def test_format_for_focus_prose_default():
    assert dw.format_for_focus("hello world") == "Hello world."
    assert dw.format_for_focus("já tem ponto.") == "Já tem ponto."
    assert dw.format_for_focus("") == ""


def test_type_text_copies_pastes_and_restores(monkeypatch):
    events = []
    monkeypatch.setattr(dw, "_get_clipboard", lambda: "OLD")
    monkeypatch.setattr(dw, "_set_clipboard", lambda t: events.append(("copy", t)))
    monkeypatch.setattr(dw, "_paste_ctrl_v", lambda: events.append(("paste", None)))
    monkeypatch.setattr(dw.time, "sleep", lambda _s: None)

    dw.type_text("olá mundo")

    assert events == [
        ("copy", "Olá mundo."),   # formatted text copied
        ("paste", None),          # Ctrl+V sent
        ("copy", "OLD"),          # previous clipboard restored
    ]


def test_type_text_survives_clipboard_read_failure(monkeypatch):
    events = []

    def boom():
        raise RuntimeError("no clipboard")

    monkeypatch.setattr(dw, "_get_clipboard", boom)
    monkeypatch.setattr(dw, "_set_clipboard", lambda t: events.append(("copy", t)))
    monkeypatch.setattr(dw, "_paste_ctrl_v", lambda: events.append(("paste", None)))
    monkeypatch.setattr(dw.time, "sleep", lambda _s: None)

    dw.type_text("teste")

    # paste still happens; no restore because the read failed
    assert events == [("copy", "Teste."), ("paste", None)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_dictation_windows.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'laris.dictation_windows'`.

- [ ] **Step 3: Implement `laris/dictation_windows.py`**

```python
"""Dictation output on Windows: clipboard + Ctrl+V. pyperclip/pynput are
imported lazily inside the seams so importing this module never loads them
(and unit tests can patch the seams without a real desktop). The PTT key on
Windows defaults to right-shift, not Ctrl, so a Ctrl+V paste never collides
with the held hotkey."""
from __future__ import annotations

import time

_PASTE_SETTLE_SECONDS = 0.3
_TERMINAL = (".", "!", "?", ":")


def format_for_focus(text: str) -> str:
    """Default prose formatting (no app detection on Windows v1): capitalize
    the first letter and add a period if the text has no terminal punctuation
    and is a single line."""
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if not text.endswith(_TERMINAL) and "\n" not in text:
        text += "."
    return text


def _get_clipboard() -> str:
    import pyperclip
    return pyperclip.paste()


def _set_clipboard(text: str) -> None:
    import pyperclip
    pyperclip.copy(text)


def _paste_ctrl_v() -> None:
    from pynput.keyboard import Controller, Key
    kb = Controller()
    with kb.pressed(Key.ctrl):
        kb.press("v")
        kb.release("v")


def type_text(text: str) -> None:
    """Paste text into the focused app via clipboard + Ctrl+V, restoring the
    previous clipboard best-effort."""
    text = format_for_focus(text)

    previous: str | None = None
    try:
        previous = _get_clipboard()
    except Exception:  # noqa: BLE001 - restore is best-effort; paste must still happen
        previous = None

    try:
        _set_clipboard(text)
        _paste_ctrl_v()
    except Exception as exc:  # noqa: BLE001 - paste failure must not kill the voice loop
        print(f"[Dictation] paste failed: {exc!r} - text left on the clipboard")
        return

    time.sleep(_PASTE_SETTLE_SECONDS)

    if previous is not None:
        try:
            _set_clipboard(previous)
        except Exception:  # noqa: BLE001 - restore is best-effort
            pass
```

- [ ] **Step 4: Add pyperclip to requirements**

In `laris/requirements.txt`, add:

```
pyperclip>=1.8
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_dictation_windows.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
cd ~/code/voxis && git add packages/laris/laris/dictation_windows.py packages/laris/requirements.txt packages/laris/tests/test_dictation_windows.py && git commit -m "feat(laris): Windows dictation output (clipboard + Ctrl+V)"
```

---

### Task 2: WindowsBackend + platform-aware activation key

**Files:**
- Create: `laris/platform/windows.py`
- Modify: `laris/config.py` (the `DICTATE_KEY` line)
- Test: `tests/test_windows_backend.py`

**Interfaces:**
- Consumes: `laris.stt_faster.FasterWhisperTranscriber` (Plan 1), `laris.dictation_windows.type_text` (Task 1), `laris.platform.base.PlatformBackend` shape.
- Produces: `laris.platform.windows.WindowsBackend` implementing the `PlatformBackend` protocol - `warm()`/`transcribe()` delegate to faster-whisper; `type_text()` delegates to `dictation_windows.type_text`; `make_overlay(url)` and `make_ducker()` return no-op objects (the orb is hosted by Tauri on Windows; per-app ducking is out of scope). `get_backend()` on `win32` (added in Plan 1) now resolves.

- [ ] **Step 1: Write the failing test**

`tests/test_windows_backend.py`:

```python
"""WindowsBackend delegation and the no-op overlay/ducker."""
import numpy as np


def test_windows_backend_delegates(monkeypatch):
    calls = {}

    class FakeStt:
        def warm(self):
            calls["warm"] = True

        def transcribe(self, audio, sample_rate):
            calls["transcribe"] = (len(audio), sample_rate)
            return "texto"

    monkeypatch.setattr("laris.stt_faster.FasterWhisperTranscriber", lambda: FakeStt())
    monkeypatch.setattr("laris.dictation_windows.type_text",
                        lambda text: calls.__setitem__("typed", text))

    from laris.platform.windows import WindowsBackend
    backend = WindowsBackend()
    backend.warm()
    assert backend.transcribe(np.zeros(8, dtype=np.float32), 16000) == "texto"
    backend.type_text("oi")
    assert calls == {"warm": True, "transcribe": (8, 16000), "typed": "oi"}


def test_windows_overlay_and_ducker_are_noops():
    from laris.platform.windows import WindowsBackend
    backend = WindowsBackend.__new__(WindowsBackend)  # skip Transcriber construction
    overlay = backend.make_overlay("http://127.0.0.1:8421/overlay")
    ducker = backend.make_ducker()
    # no-ops must accept the calls the daemon makes without raising
    overlay.show("dictate")
    overlay.hide()
    ducker.duck()
    ducker.restore()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_windows_backend.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'laris.platform.windows'`.

- [ ] **Step 3: Implement `laris/platform/windows.py`**

```python
"""Windows backend: faster-whisper STT + clipboard/Ctrl+V paste. The orb is
hosted by the Tauri tray (a transparent window), so the overlay here is a
no-op; per-app output ducking is out of scope, so the ducker is a no-op too.
Heavy imports are lazy (constructed only when this backend is)."""
from __future__ import annotations

import numpy as np


class _NoOpOverlay:
    """The orb is a Tauri window on Windows; the daemon still calls show/hide,
    so accept them and do nothing - the orb reacts to /ws/voice phase events."""
    def __init__(self, url: str) -> None:
        self.url = url

    def show(self, mode: str) -> None:
        pass

    def hide(self) -> None:
        pass


class _NoOpDucker:
    def duck(self) -> None:
        pass

    def restore(self) -> None:
        pass


class WindowsBackend:
    def __init__(self) -> None:
        from laris.stt_faster import FasterWhisperTranscriber
        self._stt = FasterWhisperTranscriber()

    def warm(self) -> None:
        self._stt.warm()

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        return self._stt.transcribe(audio, sample_rate)

    def type_text(self, text: str) -> None:
        from laris.dictation_windows import type_text
        type_text(text)

    def make_overlay(self, url: str):
        return _NoOpOverlay(url)

    def make_ducker(self):
        return _NoOpDucker()
```

- [ ] **Step 4: Make the activation-key default platform-aware in `config.py`**

In `laris/config.py`, replace the line:

```python
DICTATE_KEY = _setting("DICTATE_KEY", "cmd_r")
```

with:

```python
import sys as _sys
# cmd_r does not exist on Windows; right-shift is a comfortable PTT key there
# and is in hotkey.py's allowed set. Users change it in the tray settings.
_DEFAULT_DICTATE_KEY = "shift_r" if _sys.platform == "win32" else "cmd_r"
DICTATE_KEY = _setting("DICTATE_KEY", _DEFAULT_DICTATE_KEY)
```

(Do not remove the existing `import os` at the top; add the `import sys as _sys` locally as shown, or at the top with the other imports - either is fine, keep it minimal.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_windows_backend.py -q`
Expected: PASS (2 tests).

- [ ] **Step 6: Full fast suite green (macOS default key unchanged)**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/ -q -m "not slow" > /tmp/claude/p2-py.log 2>&1; echo exit=$?`
Expected: `exit=0`, 167 passed (162 + 3 dictation + 2 backend). On macOS `DICTATE_KEY` still defaults to `cmd_r` (verify no hotkey/config test broke).

- [ ] **Step 7: Commit**

```bash
cd ~/code/voxis && git add packages/laris/laris/platform/windows.py packages/laris/laris/config.py packages/laris/tests/test_windows_backend.py && git commit -m "feat(laris): WindowsBackend + platform-aware activation key default"
```

---

### Task 3: Tauri transparent orb window (Windows)

**Files:**
- Create: `apps/tray/src-tauri/src/overlay.rs`
- Modify: `apps/tray/src-tauri/src/lib.rs` (add `mod overlay;`, open/close from the poll loop)

**Interfaces:**
- Consumes: `laris::read_peer` (the token), `laris::alive`, the `AppState`/`Snapshot` from lib.rs.
- Produces: `overlay::open(app: &AppHandle, url: &str) -> tauri::Result<()>` (creates the transparent orb window if absent) and `overlay::close(app: &AppHandle)` (closes it if present). The poll loop opens it when laris is alive and closes it when not. Gated `#[cfg(windows)]`; on macOS these are no-ops so the pyobjc overlay is untouched.

- [ ] **Step 1: Write the module with a unit test for the URL builder**

`apps/tray/src-tauri/src/overlay.rs`:

```rust
//! Transparent orb overlay window on Windows. The orb HTML/JS is served by
//! the laris FastAPI server (/overlay); here we host it in a click-through,
//! always-on-top, transparent Tauri window. On macOS laris drives its own
//! pyobjc window, so these functions are no-ops there.

use crate::laris::LarisPeer;

/// The overlay URL the window loads, carrying the auth token the orb JS needs
/// to open the /ws/voice websocket.
pub fn overlay_url(peer: &LarisPeer) -> String {
    format!("{}/overlay?token={}", peer.url, peer.token)
}

#[cfg(windows)]
pub fn open(app: &tauri::AppHandle, url: &str) -> tauri::Result<()> {
    use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

    if app.get_webview_window("orb").is_some() {
        return Ok(());
    }
    let win = WebviewWindowBuilder::new(app, "orb", WebviewUrl::External(url.parse().unwrap()))
        .transparent(true)
        .decorations(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .focused(false)
        .resizable(false)
        .shadow(false)
        .build()?;
    // click-through: the orb never intercepts mouse input
    let _ = win.set_ignore_cursor_events(true);
    Ok(())
}

#[cfg(windows)]
pub fn close(app: &tauri::AppHandle) {
    use tauri::Manager;
    if let Some(win) = app.get_webview_window("orb") {
        let _ = win.close();
    }
}

#[cfg(not(windows))]
pub fn open(_app: &tauri::AppHandle, _url: &str) -> tauri::Result<()> {
    Ok(()) // macOS: laris hosts its own pyobjc overlay
}

#[cfg(not(windows))]
pub fn close(_app: &tauri::AppHandle) {}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::laris::LarisPeer;

    #[test]
    fn overlay_url_carries_token() {
        let peer = LarisPeer { url: "http://127.0.0.1:8421".into(), token: "abc".into() };
        assert_eq!(overlay_url(&peer), "http://127.0.0.1:8421/overlay?token=abc");
    }
}
```

- [ ] **Step 2: Run the test to verify it fails to compile (module not wired)**

Run: `cd ~/code/voxis/apps/tray/src-tauri && cargo test overlay 2>&1 | tail -5`
Expected: compile error - `overlay` module not declared in lib.rs.

- [ ] **Step 3: Wire the module and the poll loop in `lib.rs`**

Add near the other `mod` lines at the top of `apps/tray/src-tauri/src/lib.rs`:

```rust
mod overlay;
```

In the 2s poll loop closure (where the snapshot is compared and the tray menu is rebuilt on the main thread), after the menu is updated, drive the orb window from `laris_alive`. Find the `run_on_main_thread` block that rebuilds the menu and add, inside it, after the menu update:

```rust
                if current.laris_alive {
                    if let Some(peer) = laris::read_peer(&peers_path()) {
                        let _ = overlay::open(&handle2, &overlay::overlay_url(&peer));
                    }
                } else {
                    overlay::close(&handle2);
                }
```

(`handle2` is the `AppHandle` clone already used inside that closure; `peers_path()` and `laris::read_peer` are already in scope in lib.rs. If the closure uses a different handle name, use whatever `AppHandle` it already has.)

- [ ] **Step 4: Compile and run the Rust tests**

Run: `cd ~/code/voxis/apps/tray/src-tauri && cargo test 2>&1 | tail -5; echo exit=$?`
Expected: `exit=0`, 21 tests passed (20 existing + 1 overlay_url). The `#[cfg(windows)]` open/close are not compiled on macOS, but `overlay_url` and the module wiring are, so this proves it integrates without breaking the macOS build.

- [ ] **Step 5: Commit**

```bash
cd ~/code/voxis && git add apps/tray/src-tauri/src/overlay.rs apps/tray/src-tauri/src/lib.rs && git commit -m "feat(tray): transparent orb window on Windows, wired to dictation state"
```

---

## Self-review notes

- Spec coverage: implements the "platform abstraction (Windows backend)", the Windows dictation output, the platform-aware key, and the "orb overlay via a Tauri window" sections of the design. Packaging (PyInstaller + sidecar + installer) is Plan 3.
- The macOS default key (`cmd_r`) and the pyobjc overlay are unchanged; the orb window is `#[cfg(windows)]`.
- Windows runtime behavior (real Ctrl+V paste, real transparent window, mic capture) is verified in Plan 3's Windows smoke; here everything is unit-tested (Python mocks) and compile-checked (`cargo` on macOS).
- Type consistency: `WindowsBackend` matches the `PlatformBackend` methods used by `daemon.py` (warm/transcribe/type_text/make_overlay/make_ducker); the no-op overlay implements `show(mode)/hide()` and the no-op ducker `duck()/restore()`, matching what the daemon calls.
