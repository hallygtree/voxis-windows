# VOXIS on Windows

This fork adds Windows to [sammyjdev/voxis](https://github.com/sammyjdev/voxis),
next to macOS and Linux. One installer ships the tray plus both engines -
dictation (`laris`) and meetings (`miris`) - frozen with PyInstaller, so there
is no system Python, venv or source clone involved. For macOS and Linux,
follow [INSTALL.md](INSTALL.md).

---

## 1. Install

Download `VOXIS_<version>_x64_en-US.msi` (recommended) or
`VOXIS_<version>_x64-setup.exe` from the
[Releases page](https://github.com/hallygtree/voxis-windows/releases) and run
it. The build is unsigned, so SmartScreen warns once - see
[Unsigned builds](#unsigned-builds).

## 2. Allow the microphone

Windows has no accessibility prompt like macOS. Enable the microphone under
**Settings > Privacy & security > Microphone**, including **Let desktop apps
access your microphone**.

## 3. Dictate

Hold the activation key (**Right-Shift** by default), speak, release - the text
is pasted into the focused app. Change the key in the tray's
**Configurações...** window.

For hands-free, check **Hands-free (duplo-toque na tecla)** in the tray menu
(or **Permitir hands-free** in settings), then double-tap the key: VOXIS keeps
listening and types each sentence as you finish it. Tap once to stop. The
checkbox takes effect at once; it never starts listening on its own.

## 4. Record meetings (optional)

Meeting notes need an LLM CLI on your `PATH` for the summary. The default is
the [Antigravity CLI](https://antigravity.google) (`agy`), logged in; any
prompt-in / text-out CLI works.

Then use **Gravar reunião** in the tray to start and **Parar gravação** to
stop. VOXIS records your mic and the default speaker (WASAPI loopback),
splits each channel into utterances, transcribes them, summarizes, and writes
the note into your vault. **Última nota** opens the most recent one.

Config is created on first run at `~/.miris/config.toml`: vault root,
category-to-folder map, and `llm_command`. Point `vault_root` at your Obsidian
vault before the first meeting. Raw recordings stay under
`~/.miris/sessions/<timestamp>/` until you delete them.

Tip: use a headset. Without one the mic also picks up the speakers, so your
channel echoes the other side.

## First run downloads the speech model

Speech recognition runs on [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
with the Vulkan backend. On first use the engine downloads Whisper
`large-v3-turbo` (q5_0, 547 MB) from Hugging Face into
`~/.config/voice-at/models/`, and compiles its GPU shaders (about 25 s, once per
driver and build). The tray menu and its tooltip show progress while this
happens. After that it runs fully offline.

- **GPU.** Any Vulkan-capable GPU is used - NVIDIA, AMD or Intel, integrated
  graphics included. The Vulkan loader ships with the GPU driver; there is no
  CUDA or other runtime to install. A discrete card is preferred over
  integrated graphics.
- **No GPU.** Dictation falls back to Parakeet TDT v3 on the CPU (396 MB,
  downloaded only on machines that need it): much faster than Whisper on a CPU,
  but limited to 25 European languages. Meetings always use Whisper, on the CPU
  if necessary.
- **Other models.** Put another `ggml` Whisper file into the models folder and
  select it in the tray settings.

## If something breaks

The engines are windowed (no console), so they log to files. Send these when
reporting a problem:

- Dictation: `%USERPROFILE%\.config\voice-at\laris-engine.log` - startup
  output, the chosen GPU and model, and any crash traceback. The previous run
  is kept beside it as `laris-engine.log.1`.
- Meetings: `recorder.log` inside the session folder under
  `%USERPROFILE%\.miris\sessions\`.

---

## Unsigned builds

VOXIS is **not code-signed** (that needs a paid developer certificate). The app
is safe; Windows just cannot verify the publisher. On first launch SmartScreen
shows "Windows protected your PC / unknown publisher" - click **More info >
Run anyway**.

## Uninstall / reset

- Uninstall **VOXIS** from **Settings > Apps > Installed apps**.
- State and config: `~/.config/voice-at/` (settings, orb theme, downloaded
  models, logs), `~/.miris/` (meeting config and recordings), and any notes
  already written into your vault.

---

## For contributors: how the fork stays mergeable

Windows is added the way upstream added Linux: platform files of its own
(`laris/platform/windows.py`, `*_windows.py`, `requirements-windows.txt`,
`packaging/`, `tauri.windows.conf.json`, `overlay.rs`, `windows.yml`) and
small hooks in shared files (`sys.platform == "win32"`, `#[cfg(windows)]`, a
fallback where `torch` is missing). Three rules keep every sync with upstream
small:

1. **Never delete or rewrite upstream code**, macOS and Linux included. A file
   deleted here conflicts on every merge.
2. **Keep Windows code in Windows files**; a shared file gets the smallest hook
   that works.
3. **Leave upstream's tests and workflows alone.** Tests that need a
   macOS/Linux module or a POSIX shell are skipped by
   `.github/scripts/pytest_windows_skips.py`, and upstream's `tray-build.yml`
   and `linux.yml` are disabled in this fork's Actions settings.

Running the Windows tests locally (Python 3.11, from `packages/laris` or
`packages/miris`, after `pip install -r requirements-windows.txt pytest httpx`
and `pip install -e .`):

```powershell
$env:PYTHONPATH = "../../.github/scripts"
python -m pytest -q -p pytest_windows_skips --ignore-glob="*_linux*"
```

and `cargo test` in `apps/tray/src-tauri`.

### Syncing with upstream

```powershell
git fetch upstream
git switch -c sync/upstream-YYYY-MM-DD master
git merge upstream/master
```

Resolve conflicts in favour of upstream's code and put the Windows hook back
on top, then open a pull request into this fork's `master` and merge once
`windows.yml` is green. Merge, never rebase: `master` is public.
