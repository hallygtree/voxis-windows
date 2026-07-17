# VOXIS Dictation on Windows - Design

**Date:** 2026-07-17
**Status:** Draft - awaiting user review
**Scope:** Port the LARIS dictation engine to Windows as the cross-platform
beachhead. Meetings (MIRIS) are a later phase.

## Goal

A Windows user installs one file and dictates: hold a key, speak, the text
lands in the focused app, with the VOXIS orb as live feedback. No source
install, no system Python. CPU works on any machine; CUDA accelerates it when
present, detected at install time.

## Why this first

The engines are macOS-locked at the OS-API level (mlx-whisper = Apple Silicon,
Core Audio tap = macOS). The Tauri tray already ships cross-platform but has
nothing to control on Windows. Dictation is the smaller half (mic only, no
system-audio loopback), the higher-frequency feature, and validates the whole
cross-platform chain - STT, hotkey, text injection, orb, packaging - before
taking on the harder meeting-capture half.

## Scope

**In:**
- Push-to-talk dictation on Windows: hold key -> speak -> text in focused app.
- Activation-key selection (already in the tray settings window).
- The full orb overlay as feedback.
- One installable `.msi`/`.exe`, no system Python.
- CPU (int8) baseline guaranteed; CUDA opportunistic if detected at install.

**Out (deliberately deferred):**
- MIRIS meetings (needs WASAPI loopback - next phase).
- Hands-free double-tap (cheap to add later; not a requirement).
- App-aware formatting (macOS detects code-editor vs prose via NSWorkspace;
  Windows v1 applies one default formatting).
- Audio ducking (different Windows API; dropped for MVP).
- Linux (the abstraction leaves room, but not built or tested here).

## Global Constraints

- Mac path must not regress: the existing laris suite (155 tests) stays green,
  and macOS keeps mlx-whisper (measurably faster on Apple Silicon than
  faster-whisper CPU).
- All code/comments in English; UI copy pt-BR. Plain hyphen `-` only.
- No system Python on the target machine; engine ships as a PyInstaller build.
- CPU is the guaranteed baseline; CUDA is an optional acceleration, never a
  hard requirement.

## Architecture: platform abstraction layer

Today macOS-specific logic is spread across `dictation.py`, `transcriber.py`,
`app_context.py`. Instead of scattering `if sys.platform` checks, introduce a
thin package:

```
laris/platform/
  base.py       # PlatformBackend Protocol - the interface daemon consumes
  macos.py      # current behavior: CGEvent Cmd+V, mlx-whisper, NSWorkspace
  windows.py    # new: clipboard + Ctrl+V, faster-whisper, passthrough format
  __init__.py   # get_backend() -> selects by sys.platform at runtime
```

`base.PlatformBackend` (Protocol):

- `transcribe(audio: np.ndarray, sample_rate: int) -> str`
  - macOS: existing mlx-whisper `Transcriber`.
  - Windows: faster-whisper (CTranslate2), `device="cuda"` if available else
    `"cpu"` with `compute_type="int8"`, chosen at runtime.
- `type_text(text: str) -> None`
  - macOS: existing Quartz CGEvent Cmd+V + pbcopy/pbpaste.
  - Windows: set clipboard + send Ctrl+V (pynput), best-effort clipboard
    restore, same shape as the macOS path.
- `format_for_focus(text: str) -> str`
  - macOS: existing app-aware formatting.
  - Windows: default formatting (basic punctuation/capitalization), no app
    detection in v1.

`daemon.py` / `state_machine.py` stop importing `dictation`/`transcriber`
directly and receive a `PlatformBackend` from `get_backend()`. Everything else
in the dictation path is already cross-platform and unchanged: `hotkey.py`
(pynput), `audio_capture.py` (sounddevice), VAD (silero-vad), noise reduction
(deepfilternet), `server.py` (FastAPI), `orb_theme.py`, `settings.py`.

The hotkey key names are already validated in `hotkey.py`; the allowed set
(`cmd_r`, `shift_r`, `f13`, ...) maps to pynput keys that also exist on
Windows. The tray settings window already offers this selector.

## STT backend: faster-whisper

- Windows/Linux backend is faster-whisper (CTranslate2). Runtime device
  selection: `WhisperModel(model, device="cuda", compute_type="float16")` when
  CUDA is present, else `device="cpu", compute_type="int8"`.
- Default model: `small` (best pt-BR quality/latency balance on CPU; `base` is
  weaker in Portuguese). Configurable via the existing `STT_MODEL` env/setting
  so slow machines can drop to `base`. Model files download from HuggingFace
  on first run (standard faster-whisper behavior).
- macOS keeps mlx-whisper (`whisper-large-v3-turbo-q4`) - unchanged.
- `config.STT_LANGUAGE` semantics carry over ("" = auto-detect, default "pt").

## Orb overlay via a Tauri window

The orb rendering (`frontend/voice-orb.js`, theme engine, canvas/WebGL) and
the FastAPI server that serves `/overlay` + streams `/ws/voice` are already
cross-platform and unchanged. Only the window that hosts them is macOS-locked
(`overlay_app.py` uses a pyobjc WKWebView).

On Windows, the existing Tauri tray creates a transparent, always-on-top,
click-through, non-taskbar webview window pointing at
`http://127.0.0.1:8421/overlay?token=<token>`:

- Window flags: `transparent: true`, `decorations: false`,
  `always_on_top: true`, `skip_taskbar: true`, focus disabled, plus
  `set_ignore_cursor_events(true)` for click-through.
- Token: the tray already reads the laris token from
  `~/.config/voice-at/peers.json` (used for the theme API).
- Size/position: read from `orb-theme.json` (same file the theme API writes),
  reusing `position_rect` semantics.
- The orb JS connects to `ws://127.0.0.1:8421/ws/voice?token=...` from inside
  the webview, exactly as on macOS - no new plumbing.

The macOS pyobjc overlay path is untouched; this only adds the Tauri-hosted
path for Windows. (Unifying macOS onto the Tauri window later is possible but
out of scope here.)

## Packaging and install (approach A: single installer)

- The Python engine is built with PyInstaller (onedir): a self-contained
  folder with the engine executable, its deps, and CPU CTranslate2. No system
  Python required.
- The engine ships as a **Tauri sidecar** inside the tray app, so one
  `.msi`/`.exe` installs tray + engine. The friend downloads one file.
- CPU (int8) is bundled = guaranteed baseline, works offline after the model
  download.
- CUDA is opportunistic: on post-install / first run, detect an NVIDIA CUDA
  runtime; if present, download and swap in the CUDA CTranslate2 runtime as
  acceleration. If absent or the download fails, stay on CPU. Never blocks.
- The model (`small`, a few hundred MB) downloads on first run.
- The tray spawns/controls the engine on Windows the same way it does on macOS
  (via the sidecar path instead of `tray.json`'s `laris_dir` venv python).

This is the most complex part of the project (PyInstaller + Tauri sidecar +
CUDA runtime swap). It is where the "download and use" promise lives, so the
complexity is load-bearing, not incidental.

Permissions note: Windows has no macOS TCC prompt; microphone access is
granted under Settings > Privacy > Microphone. Documented in INSTALL.md.

## Testing

- Unit tests for the platform backends: `windows.format_for_focus` and the
  clipboard/Ctrl+V assembly are testable with mocks, no real OS needed.
- faster-whisper `transcribe`: smoke test on a short known WAV -> expected text.
- The existing laris suite (155) stays green on macOS - the abstraction must
  not regress the macOS path (assert `get_backend()` returns the macOS backend
  and the existing dictation/transcriber behavior is unchanged there).
- Manual Windows smoke: install the `.msi`, hold the key, speak, confirm text
  in Notepad and the orb appearing/reacting.

## Risks / open questions for the plan

- PyInstaller + faster-whisper/CTranslate2 hidden-import and DLL bundling is
  fiddly; the plan should include a dedicated "engine builds and runs frozen"
  task before wiring the sidecar.
- CUDA runtime swap without system Python needs care; if it proves too fragile
  for v1, fall back to "CPU-only installer, CUDA documented as a manual
  upgrade" without changing the rest of the design.
- Tauri sidecar + a long-lived Python process: confirm lifecycle (the tray
  already manages a `LarisDaemon` child on macOS; the Windows sidecar reuses
  that ownership model).
