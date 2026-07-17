# Windows Dictation P1 - Platform Abstraction + faster-whisper STT

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a platform-backend abstraction in laris and add a cross-platform faster-whisper STT backend, with the macOS path unchanged - the foundation the Windows dictation port builds on.

**Architecture:** A thin `laris/platform/` package exposes a `PlatformBackend` selected by `sys.platform`. `daemon.run()`/`run_always_on()` consume the backend instead of importing macOS modules directly. The macOS backend wraps the existing `Transcriber`/`type_text`/`Overlay`/`AudioDucker` (behavior identical). A new `laris/stt_faster.py` provides a faster-whisper transcriber matching the existing `Transcriber` interface, runtime-tested on macOS CPU (it selects CUDA on Windows).

**Tech Stack:** Python 3.11, faster-whisper (CTranslate2), numpy, pytest. macOS keeps mlx-whisper.

## Global Constraints

- macOS path must not regress: the existing laris suite (155 tests) stays green.
- macOS keeps mlx-whisper (faster on Apple Silicon); faster-whisper is the Windows/Linux backend, not a macOS replacement.
- All code/comments in English; UI copy pt-BR. Plain hyphen `-` only, never em/en dashes.
- Run pytest with `HF_HUB_DISABLE_XET=1` on this machine (hf_xet TLS hang).
- CPU is the guaranteed STT baseline; CUDA is opportunistic (`device="cuda"` when available, else `"cpu"` int8), selected at runtime.
- `config.STT_LANGUAGE` semantics carry over: "" = auto-detect, default "pt".

## File Structure

```
laris/platform/__init__.py   # NEW - get_backend() selects by sys.platform
laris/platform/base.py       # NEW - PlatformBackend Protocol
laris/platform/macos.py      # NEW - MacOSBackend wrapping existing modules
laris/stt_faster.py          # NEW - FasterWhisperTranscriber (warm/transcribe)
laris/daemon.py              # MODIFY - consume get_backend() instead of direct imports
laris/requirements.txt       # MODIFY - add faster-whisper (extras: windows/linux)
tests/test_platform.py       # NEW
tests/test_stt_faster.py     # NEW
```

Note: `WindowsBackend` (which needs the Windows dictation/paste path) lands in Plan 2. This plan delivers the abstraction, the macOS backend, and the reusable faster-whisper transcriber component.

---

### Task 1: Platform backend abstraction (macOS backend, daemon rewired)

**Files:**
- Create: `laris/platform/__init__.py`, `laris/platform/base.py`, `laris/platform/macos.py`
- Modify: `laris/daemon.py` (the two `from laris.X import Y` blocks inside `run()` and `run_always_on()`, and their `stt`/`type_text`/`Overlay`/`AudioDucker` uses)
- Test: `tests/test_platform.py`

**Interfaces:**
- Produces:
  - `laris.platform.base.PlatformBackend` (Protocol) with:
    - `warm(self) -> None`
    - `transcribe(self, audio: np.ndarray, sample_rate: int) -> str`
    - `type_text(self, text: str) -> None`
    - `make_overlay(self, url: str) -> OverlayLike` (has `show(mode: str)`, `hide()`)
    - `make_ducker(self) -> DuckerLike` (has `duck()`, `restore()`)
  - `laris.platform.get_backend() -> PlatformBackend` (selects by `sys.platform`; raises `SystemExit` on unsupported)
  - `laris.platform.macos.MacOSBackend` implementing the Protocol by delegating to existing `laris.transcriber.Transcriber`, `laris.dictation.type_text`, `laris.overlay.Overlay`, `laris.ducking.AudioDucker`.
- Consumes: existing `laris.transcriber.Transcriber().warm()/.transcribe(audio, sample_rate)`, `laris.dictation.type_text(text)`, `laris.overlay.Overlay(url).show(mode)/.hide()`, `laris.ducking.AudioDucker().duck()/.restore()`.

- [ ] **Step 1: Write the failing test**

`tests/test_platform.py`:

```python
"""Platform backend selection and the macOS backend's delegation."""
import sys
import types

import numpy as np
import pytest

from laris import platform as laris_platform
from laris.platform.macos import MacOSBackend


def test_get_backend_darwin_returns_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    backend = laris_platform.get_backend()
    assert isinstance(backend, MacOSBackend)


def test_get_backend_unsupported_exits(monkeypatch):
    monkeypatch.setattr(sys, "platform", "sunos")
    with pytest.raises(SystemExit):
        laris_platform.get_backend()


def test_macos_backend_delegates(monkeypatch):
    calls = {}

    class FakeStt:
        def warm(self):
            calls["warm"] = True

        def transcribe(self, audio, sample_rate):
            calls["transcribe"] = (len(audio), sample_rate)
            return "hello"

    # patch the lazily-imported dependencies the backend delegates to
    monkeypatch.setattr("laris.transcriber.Transcriber", lambda: FakeStt())
    monkeypatch.setattr("laris.dictation.type_text",
                        lambda text: calls.__setitem__("typed", text))

    backend = MacOSBackend()
    backend.warm()
    assert backend.transcribe(np.zeros(10, dtype=np.float32), 16000) == "hello"
    backend.type_text("hi there")
    assert calls == {"warm": True, "transcribe": (10, 16000), "typed": "hi there"}


def test_macos_backend_overlay_and_ducker_are_real_types():
    from laris.overlay import Overlay
    from laris.ducking import AudioDucker

    backend = MacOSBackend.__new__(MacOSBackend)  # no Transcriber construction
    assert isinstance(backend.make_overlay("http://x"), Overlay)
    assert isinstance(backend.make_ducker(), AudioDucker)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_platform.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'laris.platform'`.

- [ ] **Step 3: Write `laris/platform/base.py`**

```python
"""The interface the daemon consumes, so it never imports OS-specific
modules directly. One implementation per platform (macos, windows)."""
from __future__ import annotations

from typing import Protocol

import numpy as np


class OverlayLike(Protocol):
    def show(self, mode: str) -> None: ...
    def hide(self) -> None: ...


class DuckerLike(Protocol):
    def duck(self) -> None: ...
    def restore(self) -> None: ...


class PlatformBackend(Protocol):
    def warm(self) -> None: ...
    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str: ...
    def type_text(self, text: str) -> None: ...
    def make_overlay(self, url: str) -> OverlayLike: ...
    def make_ducker(self) -> DuckerLike: ...
```

- [ ] **Step 4: Write `laris/platform/macos.py`**

```python
"""macOS backend: delegates to the existing mlx-whisper transcriber, the
CGEvent paste path, the AppKit overlay and the osascript ducker. Behavior
is identical to the pre-abstraction laris - this is a wrapper, not a change."""
from __future__ import annotations

import numpy as np


class MacOSBackend:
    def __init__(self) -> None:
        from laris.transcriber import Transcriber
        self._stt = Transcriber()

    def warm(self) -> None:
        self._stt.warm()

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        return self._stt.transcribe(audio, sample_rate)

    def type_text(self, text: str) -> None:
        from laris.dictation import type_text
        type_text(text)

    def make_overlay(self, url: str):
        from laris.overlay import Overlay
        return Overlay(url=url)

    def make_ducker(self):
        from laris.ducking import AudioDucker
        return AudioDucker()
```

- [ ] **Step 5: Write `laris/platform/__init__.py`**

```python
"""Selects the platform backend at runtime. Import is lazy so importing
this package never pulls mlx (macOS) or ctranslate2 (windows) unless the
matching backend is actually constructed."""
from __future__ import annotations

import sys

from laris.platform.base import PlatformBackend


def get_backend() -> PlatformBackend:
    if sys.platform == "darwin":
        from laris.platform.macos import MacOSBackend
        return MacOSBackend()
    if sys.platform == "win32":
        from laris.platform.windows import WindowsBackend  # lands in Plan 2
        return WindowsBackend()
    raise SystemExit(f"[laris] unsupported platform: {sys.platform}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_platform.py -q`
Expected: PASS (4 tests). The `win32` branch imports a not-yet-existing module, but no test hits it (only darwin/sunos are exercised).

- [ ] **Step 7: Rewire `daemon.py` to consume the backend**

In `laris/daemon.py`, `run()`: replace the import block and the direct constructions. Change:

```python
    from laris.dictation import type_text
    from laris.ducking import AudioDucker
    from laris.hotkey import PushToTalk
    from laris.overlay import Overlay
    from laris.transcriber import Transcriber

    if voice_queue is None:
        import queue
        voice_queue = queue.Queue()

    stt = Transcriber()
    stt.warm()
    voice_session = make_voice_session()
    assistant = make_assistant()
    overlay = Overlay(url=overlay_url)
    ducker = AudioDucker()
```

to:

```python
    from laris.hotkey import PushToTalk
    from laris.platform import get_backend

    if voice_queue is None:
        import queue
        voice_queue = queue.Queue()

    backend = get_backend()
    backend.warm()
    stt = backend
    type_text = backend.type_text
    voice_session = make_voice_session()
    assistant = make_assistant()
    overlay = backend.make_overlay(overlay_url)
    ducker = backend.make_ducker()
```

`stt.transcribe(...)`, `type_text(...)`, `overlay.show/hide`, `ducker.duck/restore` calls downstream are unchanged (the backend exposes `transcribe`, and `type_text` is now a bound method with the same signature).

In `run_always_on()`, replace:

```python
    from laris.audio_capture import VadCapture
    from laris.transcriber import Transcriber
    ...
    stt = Transcriber()
    stt.warm()
```

with:

```python
    from laris.audio_capture import VadCapture
    from laris.platform import get_backend
    ...
    backend = get_backend()
    backend.warm()
    stt = backend
```

- [ ] **Step 8: Run the full suite to prove macOS behavior is unchanged**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/ -q > /tmp/claude/p1-t1.log 2>&1; echo exit=$?`
Expected: `exit=0`, 159 passed (155 existing + 4 new). If any existing daemon test fails, the rewire changed behavior - fix until green.

- [ ] **Step 9: Commit**

```bash
cd ~/code/voxis && git add packages/laris && git commit -m "refactor(laris): platform backend abstraction, macOS behavior unchanged"
```

---

### Task 2: faster-whisper transcriber component

**Files:**
- Create: `laris/stt_faster.py`
- Modify: `laris/requirements.txt` (add faster-whisper)
- Test: `tests/test_stt_faster.py`

**Interfaces:**
- Produces: `laris.stt_faster.FasterWhisperTranscriber` with `warm() -> None` and `transcribe(audio: np.ndarray, sample_rate: int = 16000) -> str`, same shape as `laris.transcriber.Transcriber`. Device auto-selected: `cuda`/`float16` when available, else `cpu`/`int8`. Plan 2's `WindowsBackend` consumes this.
- Consumes: `config.STT_LANGUAGE` ("" = auto-detect), `config.SAMPLE_RATE`. Model id comes from a new `config.STT_MODEL_FASTER` (default `"small"`) so the macOS `STT_MODEL` (an mlx repo id) is not reused for faster-whisper.

- [ ] **Step 1: Add the faster-whisper model setting to config**

In `laris/config.py`, after the existing `STT_MODEL` line, add:

```python
# faster-whisper model id for the Windows/Linux backend (a plain size name,
# not the mlx repo id STT_MODEL holds). "small" balances pt-BR quality and
# CPU latency; drop to "base" on slow machines.
STT_MODEL_FASTER: str = _setting("STT_MODEL_FASTER", "small")
```

- [ ] **Step 2: Write the failing test**

`tests/test_stt_faster.py`:

```python
"""faster-whisper transcriber - device selection logic (mocked) and a real
CPU smoke transcription. The real-model test is marked slow."""
import numpy as np
import pytest


def test_device_selection_prefers_cuda_when_available(monkeypatch):
    import laris.stt_faster as mod

    captured = {}

    class FakeModel:
        def __init__(self, model, device, compute_type, **kw):
            captured.update(device=device, compute_type=compute_type, model=model)

    monkeypatch.setattr(mod, "_cuda_available", lambda: True)
    monkeypatch.setattr(mod, "WhisperModel", FakeModel)
    mod.FasterWhisperTranscriber()
    assert captured["device"] == "cuda"
    assert captured["compute_type"] == "float16"


def test_device_selection_falls_back_to_cpu(monkeypatch):
    import laris.stt_faster as mod

    captured = {}

    class FakeModel:
        def __init__(self, model, device, compute_type, **kw):
            captured.update(device=device, compute_type=compute_type)

    monkeypatch.setattr(mod, "_cuda_available", lambda: False)
    monkeypatch.setattr(mod, "WhisperModel", FakeModel)
    mod.FasterWhisperTranscriber()
    assert captured["device"] == "cpu"
    assert captured["compute_type"] == "int8"


def test_transcribe_empty_returns_empty(monkeypatch):
    import laris.stt_faster as mod
    monkeypatch.setattr(mod, "_cuda_available", lambda: False)
    monkeypatch.setattr(mod, "WhisperModel", lambda *a, **k: object())
    t = mod.FasterWhisperTranscriber()
    assert t.transcribe(np.zeros(0, dtype=np.float32), 16000) == ""


@pytest.mark.slow
def test_real_cpu_transcription_smoke():
    """Downloads the real model once and transcribes 1s of a sine sweep -
    asserts it returns a string without raising. Runtime-verifiable on macOS
    CPU; the same code path selects CUDA on Windows."""
    from laris.stt_faster import FasterWhisperTranscriber
    t = FasterWhisperTranscriber()
    t.warm()
    audio = (0.1 * np.sin(2 * np.pi * 220 * np.arange(16000) / 16000)).astype(np.float32)
    result = t.transcribe(audio, 16000)
    assert isinstance(result, str)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_stt_faster.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'laris.stt_faster'`.

- [ ] **Step 4: Add faster-whisper to requirements and install it**

In `laris/requirements.txt`, add:

```
faster-whisper>=1.2.0
```

Install on the host (the Codex sandbox has no network):

```bash
cd ~/code/voxis/packages/laris && .venv/bin/pip install "faster-whisper>=1.2.0"
```

- [ ] **Step 5: Write `laris/stt_faster.py`**

```python
"""Cross-platform STT via faster-whisper (CTranslate2). The Windows/Linux
backend; macOS keeps mlx-whisper (transcriber.py). Device is chosen at
runtime: CUDA float16 when present, else CPU int8."""
from __future__ import annotations

import numpy as np

from faster_whisper import WhisperModel

from laris import config


def _cuda_available() -> bool:
    """True if a usable CUDA runtime is present. Best-effort: any failure
    (no driver, no NVIDIA GPU, ctranslate2 built CPU-only) means CPU."""
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # noqa: BLE001 - absence of CUDA is the common case, not an error
        return False


class FasterWhisperTranscriber:
    def __init__(self) -> None:
        if _cuda_available():
            device, compute_type = "cuda", "float16"
        else:
            device, compute_type = "cpu", "int8"
        self._model = WhisperModel(
            config.STT_MODEL_FASTER, device=device, compute_type=compute_type
        )

    def warm(self) -> None:
        """Force model load + first inference so the first real utterance
        doesn't pay it."""
        self.transcribe(np.zeros(config.SAMPLE_RATE // 2, dtype=np.float32),
                        config.SAMPLE_RATE)

    def transcribe(self, audio: np.ndarray, sample_rate: int = config.SAMPLE_RATE) -> str:
        if len(audio) == 0:
            return ""
        segments, _info = self._model.transcribe(
            audio.astype(np.float32),
            language=config.STT_LANGUAGE or None,  # "" -> auto-detect
            task="transcribe",
            condition_on_previous_text=False,  # same anti-repetition fix as mlx path
        )
        return "".join(seg.text for seg in segments).strip()
```

- [ ] **Step 6: Run the fast tests to verify they pass**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_stt_faster.py -q -m "not slow"`
Expected: PASS (3 tests; the slow real-model test is deselected).

- [ ] **Step 7: Run the real-model smoke once (host, downloads the model)**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_stt_faster.py::test_real_cpu_transcription_smoke -q`
Expected: PASS - proves faster-whisper installs, downloads `small`, and transcribes on macOS CPU. This is the runtime proof that the Windows STT backend works, validated here.

- [ ] **Step 8: Register the `slow` marker to avoid pytest warnings**

If `pytest.ini`/`pyproject.toml` has no `markers` entry, add to `laris/pyproject.toml` under `[tool.pytest.ini_options]` (create the table if absent):

```toml
markers = ["slow: real-model tests that download weights and run inference"]
```

- [ ] **Step 9: Full suite green**

Run: `cd ~/code/voxis/packages/laris && HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/ -q -m "not slow" > /tmp/claude/p1-t2.log 2>&1; echo exit=$?`
Expected: `exit=0`, 162 passed (159 + 3 fast new).

- [ ] **Step 10: Commit**

```bash
cd ~/code/voxis && git add packages/laris && git commit -m "feat(laris): faster-whisper transcriber component (cross-platform STT)"
```

---

## Self-review notes

- Spec coverage: this plan implements the "platform abstraction layer" and "STT backend: faster-whisper" sections of the spec; the orb window, Windows dictation, and packaging are explicitly Plan 2.
- The macOS `Transcriber` and `STT_MODEL` (mlx repo id) are untouched; faster-whisper uses the separate `STT_MODEL_FASTER`.
- `WindowsBackend` is referenced only inside the `win32` branch of `get_backend()` and never imported on macOS, so its absence does not break this plan.
