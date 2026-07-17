# Windows Dictation - Plan 3: Packaging (PyInstaller engine + Tauri bundle + CI installer)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a single downloadable Windows installer (`.msi`/`.exe`) that installs the VOXIS tray plus a frozen, self-contained LARIS dictation engine, with no system Python on the target machine.

**Architecture:** The Python engine is frozen with PyInstaller (onedir, torch-free) into a self-contained folder. On Windows only, a Tauri config overlay bundles that folder as an app *resource*; the tray resolves the engine executable from its resource directory and spawns it exactly the way it spawns the venv python on macOS. The macOS and Linux paths are untouched - all packaging risk is isolated to Windows. CI builds the frozen engine on the Windows runner before `tauri-action` assembles the installer.

**Tech Stack:** PyInstaller (onedir), faster-whisper/CTranslate2 (CPU int8), Tauri v2 (`resources` + platform config overlay), GitHub Actions (`tauri-action`).

## Global Constraints

- Mac path must not regress: the existing laris + tray suites stay green; macOS keeps mlx-whisper and the venv-python spawn.
- All code/comments in English; UI copy pt-BR. Plain hyphen `-` only, never em/en dashes.
- No system Python on the target machine; the engine ships frozen.
- CPU int8 is the guaranteed baseline. CUDA is a documented manual upgrade for v1, not bundled.
- The Windows engine bundle is torch-free: no torch, torchaudio, silero-vad, deepfilternet, mlx, or pyobjc. (PTT needs none of them; VAD/hands-free is out of scope; denoise degrades to passthrough.)
- Executors do NOT commit or push. The orchestrator (Claude) commits one commit per task and drives the CI loop.

## Output contract (shared by all three tasks)

These exact paths and names are the interface between the Python build (Task 1),
the Tauri config + tray spawn (Task 2), and CI (Task 3). Do not vary them.

- PyInstaller onedir output: `packages/laris/dist/laris-engine/` containing the
  executable `laris-engine.exe` (Windows) / `laris-engine` (unix).
- CI stages that folder into the tray at: `apps/tray/src-tauri/engine/`
  (so the executable lands at `apps/tray/src-tauri/engine/laris-engine.exe`).
- Tauri (Windows overlay) bundles `engine/` as a resource; at runtime the tray
  resolves the engine at `<resource_dir>/engine/laris-engine.exe`.
- The engine's CLI entry is `laris-engine` with no arguments - it runs the same
  `laris.__main__:main` the venv path runs via `python -m laris`.

---

## Task 1: Torch-free Windows engine build (PyInstaller)

**Owner:** Gemini (Python). Works only under `packages/laris/`.

**Files:**
- Create: `packages/laris/requirements-windows.txt`
- Create: `packages/laris/packaging/laris.spec`
- Create: `packages/laris/packaging/entry.py`
- Create: `packages/laris/packaging/README.md`
- Modify: `packages/laris/laris/config.py` (one platform-aware default)
- Modify: `packages/laris/.gitignore` (add `dist/`, `build/`) - create if absent
- Test: `packages/laris/tests/test_config_windows_defaults.py`

**Interfaces:**
- Consumes: `laris.__main__:main` (existing entrypoint), `config.NOISE_REDUCTION`.
- Produces: a PyInstaller onedir at `dist/laris-engine/laris-engine[.exe]` whose
  entry runs `laris.__main__:main`. The frozen exe takes no arguments.

- [ ] **Step 1: Write the failing config test**

```python
# packages/laris/tests/test_config_windows_defaults.py
"""On Windows the torch-based denoiser is not bundled, so NOISE_REDUCTION must
default off there (it would otherwise warn once per utterance). macOS keeps it
on. The env override still wins on both."""
import importlib
import sys


def _reload_config_as(platform_name, monkeypatch, env=None):
    monkeypatch.setattr(sys, "platform", platform_name)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    import laris.config as cfg
    return importlib.reload(cfg)


def test_noise_reduction_defaults_off_on_windows(monkeypatch):
    cfg = _reload_config_as("win32", monkeypatch)
    assert cfg.NOISE_REDUCTION == "off"


def test_noise_reduction_defaults_on_elsewhere(monkeypatch):
    cfg = _reload_config_as("darwin", monkeypatch)
    assert cfg.NOISE_REDUCTION == "on"


def test_noise_reduction_env_override_wins_on_windows(monkeypatch):
    cfg = _reload_config_as("win32", monkeypatch, {"NOISE_REDUCTION": "on"})
    assert cfg.NOISE_REDUCTION == "on"


def teardown_module(module):
    # leave the real platform config loaded for the rest of the suite
    import importlib
    import laris.config
    importlib.reload(laris.config)
```

- [ ] **Step 2: Run it, watch it fail**

Run: `HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_config_windows_defaults.py -q`
Expected: FAIL (NOISE_REDUCTION is currently an unconditional `"on"`).

- [ ] **Step 3: Make NOISE_REDUCTION platform-aware in `laris/config.py`**

Find the line:
```python
NOISE_REDUCTION: str = _setting("NOISE_REDUCTION", "on")  # "on" | "off"
```
Replace with (keep the same import style used elsewhere in the file for `sys`):
```python
import sys as _sys
# The Windows engine bundle is torch-free (no DeepFilterNet), so denoise there
# degrades to passthrough and would warn once per utterance. Default it off on
# Windows; keep it on where torch is available. Env override wins either way.
_DEFAULT_NOISE_REDUCTION = "off" if _sys.platform == "win32" else "on"
NOISE_REDUCTION: str = _setting("NOISE_REDUCTION", _DEFAULT_NOISE_REDUCTION)  # "on" | "off"
```

- [ ] **Step 4: Run the test, watch it pass**

Run: `HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/test_config_windows_defaults.py -q`
Expected: 3 passed.

- [ ] **Step 5: Write `packages/laris/requirements-windows.txt`**

The torch-free runtime closure for the Windows PTT engine. No pyobjc, no mlx,
no torch/torchaudio, no silero-vad, no deepfilternet. faster-whisper pulls
ctranslate2, av, tokenizers, huggingface-hub, onnxruntime transitively.

```
# Windows/Linux dictation runtime - torch-free (PTT path only).
# Heavy macOS-only deps (pyobjc-*, mlx*) and torch-based VAD/denoise
# (silero-vad, deepfilternet, torch, torchaudio) are deliberately excluded.
faster-whisper>=1.2.1
sounddevice>=0.4.6
pynput>=1.8.2
pyperclip>=1.8
numpy>=1.24.0
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
```

- [ ] **Step 6: Write `packages/laris/packaging/entry.py`**

A tiny frozen entrypoint. PyInstaller freezes a script, not a `-m` module; this
script simply calls the existing `main()`.

```python
"""PyInstaller entrypoint for the frozen laris engine. Equivalent to
`python -m laris`: boots the overlay server and runs the PTT voice loop."""
from laris.__main__ import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Write `packages/laris/packaging/laris.spec`**

PyInstaller onedir spec. `collect_all` on the native-heavy packages is the
robust choice: it pulls their submodules, data files, and bundled DLLs so the
frozen exe finds CTranslate2/PortAudio/PyAV/onnxruntime at runtime. `noarchive`
is left default. The spec is path-relative to `packages/laris/`.

```python
# -*- mode: python ; coding: utf-8 -*-
# PyInstaller onedir spec for the torch-free laris dictation engine.
# Build from packages/laris/:  pyinstaller packaging/laris.spec --noconfirm
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# Native-heavy runtime deps: bundle everything they ship (submodules + data + DLLs).
for pkg in ("faster_whisper", "ctranslate2", "av", "onnxruntime", "sounddevice"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# uvicorn resolves its protocol/loop implementations by string at runtime.
hiddenimports += collect_submodules("uvicorn")
hiddenimports += ["tokenizers", "huggingface_hub"]

a = Analysis(
    ["entry.py"],
    pathex=[".."],  # so `import laris` resolves against packages/laris/
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=[
        # keep the bundle lean and portable: never drag torch/mlx/pyobjc in
        "torch", "torchaudio", "silero_vad", "df", "deepfilternet",
        "mlx", "mlx_whisper", "AppKit", "WebKit", "objc", "Foundation",
        "Quartz", "ApplicationServices",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="laris-engine",
    console=False,  # no console window on Windows; logs go to the tray's log
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="laris-engine",
)
```

- [ ] **Step 8: Write `packages/laris/packaging/README.md`**

Document the one-command build and the torch-free/CPU-only decisions so future
maintainers (and the CI step) share the same contract.

```markdown
# Windows engine packaging

Freeze the torch-free dictation engine into a self-contained folder that ships
inside the VOXIS tray installer. No system Python on the target machine.

## Build (on Windows, or any host for a native engine)

```
cd packages/laris
python -m venv .venv-build
.venv-build\Scripts\pip install -r requirements-windows.txt pyinstaller
.venv-build\Scripts\pyinstaller packaging/laris.spec --noconfirm
```

Output: `dist/laris-engine/laris-engine.exe` plus its `_internal/` deps.

## Decisions

- Torch-free: the PTT path needs no torch. VAD (silero) is hands-free only
  (out of scope) and denoise (DeepFilterNet) degrades to passthrough, so
  torch/torchaudio/silero-vad/deepfilternet are excluded. Installer stays lean.
- CPU int8 baseline: CTranslate2 CPU is bundled and guaranteed. CUDA is a
  manual upgrade (install the CUDA CTranslate2 runtime), not bundled in v1.
- The Whisper model (`small`, a few hundred MB) downloads from HuggingFace on
  first run - not bundled.
```

- [ ] **Step 9: Ensure `.gitignore` excludes build artifacts**

Add to `packages/laris/.gitignore` (create the file if it does not exist):
```
dist/
build/
.venv-build/
```

- [ ] **Step 10: Run the full fast suite**

Run: `HF_HUB_DISABLE_XET=1 .venv/bin/python -m pytest tests/ -q -m "not slow"`
Expected: all previously-passing tests still pass, plus the 3 new config tests.
Report the exact count. (Note: the frozen build itself cannot be exercised on
macOS - it is validated in CI on the Windows runner. This task's local proof is
the config tests + a clean suite + a syntactically valid spec: verify the spec
parses with `python -c "compile(open('packaging/laris.spec').read(), 'laris.spec', 'exec')"`.)

---

## Task 2: Tray spawns the frozen engine on Windows

**Owner:** Codex (Rust + Tauri config). Works only under `apps/tray/`.

**Files:**
- Create: `apps/tray/src-tauri/tauri.windows.conf.json`
- Modify: `apps/tray/src-tauri/src/laris.rs` (platform-aware spawn)
- Modify: `apps/tray/src-tauri/src/lib.rs` (resolve engine path, pass to daemon)
- Create: `apps/tray/src-tauri/.gitignore` entry for `engine/` (append or create)

**Interfaces:**
- Consumes: the output contract - a frozen exe at `<resource_dir>/engine/laris-engine.exe`.
- Produces: nothing new for later tasks; CI (Task 3) relies on the resource
  path `engine/` declared in `tauri.windows.conf.json`.

- [ ] **Step 1: Read the current spawn and daemon wiring**

Read `apps/tray/src-tauri/src/laris.rs` (`LarisDaemon::new`, `spawn`) and the
`lib.rs` block near `LarisDaemon::new(PathBuf::from(&config.laris_dir))`
(around line 286) to see where the daemon is constructed and whether an
`AppHandle` is in scope there (it is - that block runs during setup).

- [ ] **Step 2: Write the failing test for engine-path spawn**

Add to the `#[cfg(test)] mod tests` in `apps/tray/src-tauri/src/laris.rs`:

```rust
    #[cfg(unix)]
    #[test]
    fn daemon_spawns_explicit_engine_binary() {
        use std::fs;
        use std::os::unix::fs::PermissionsExt;

        let tmp = tempfile::tempdir().unwrap();
        let engine = tmp.path().join("laris-engine");
        fs::write(&engine, "#!/bin/sh\nsleep 60\n").unwrap();
        fs::set_permissions(&engine, fs::Permissions::from_mode(0o755)).unwrap();

        // when given an explicit engine binary, the daemon runs it directly
        // instead of `.venv/bin/python -m laris`
        let mut daemon = LarisDaemon::with_engine(engine.clone());
        assert!(!daemon.owns_running());
        daemon.spawn().unwrap();
        assert!(daemon.owns_running());
        daemon.stop();
        assert!(!daemon.owns_running());
    }
```

- [ ] **Step 3: Run it, watch it fail**

Run: `cd apps/tray/src-tauri && cargo test daemon_spawns_explicit_engine_binary`
Expected: FAIL to compile - `with_engine` does not exist.

- [ ] **Step 4: Add the engine-binary spawn path to `laris.rs`**

Give `LarisDaemon` an optional engine binary. When set, `spawn()` runs it
directly (no args, its own dir); when unset, keep the existing
`.venv/bin/python -m laris` behavior verbatim.

Change the struct and constructors:
```rust
pub struct LarisDaemon {
    child: Option<Child>,
    laris_dir: PathBuf,
    engine_bin: Option<PathBuf>, // frozen engine (Windows); None = dev venv python
}

impl LarisDaemon {
    pub fn new(laris_dir: PathBuf) -> Self {
        Self { child: None, laris_dir, engine_bin: None }
    }

    /// Run a self-contained frozen engine binary (Windows packaged build).
    pub fn with_engine(engine_bin: PathBuf) -> Self {
        Self {
            child: None,
            laris_dir: engine_bin.parent().map(Path::to_path_buf).unwrap_or_default(),
            engine_bin: Some(engine_bin),
        }
    }
```

Change `spawn()` to branch on `engine_bin`:
```rust
    pub fn spawn(&mut self) -> Result<(), String> {
        if self.owns_running() {
            return Ok(()); // don't orphan a live child by overwriting its handle
        }
        let child = match &self.engine_bin {
            Some(bin) => Command::new(bin)
                .current_dir(&self.laris_dir)
                .spawn()
                .map_err(|e| format!("{}: {e}", bin.display()))?,
            None => {
                let python = self.laris_dir.join(".venv/bin/python");
                Command::new(&python)
                    .args(["-m", "laris"])
                    .current_dir(&self.laris_dir)
                    .spawn()
                    .map_err(|e| format!("{}: {e}", python.display()))?
            }
        };
        self.child = Some(child);
        Ok(())
    }
```

- [ ] **Step 5: Run the new test + the existing lifecycle test**

Run: `cd apps/tray/src-tauri && cargo test`
Expected: PASS - the new test plus all 21 existing tests (macOS venv path
unchanged, still covered by `daemon_spawn_owns_stop_lifecycle`).

- [ ] **Step 6: Resolve the engine path on Windows in `lib.rs`**

At the daemon construction site (near line 286, where `AppHandle`/`app` is in
scope during `setup`), select `with_engine` on Windows when the bundled engine
exists, else fall back to the existing venv path. Use the exact `AppHandle`
variable name present there.

```rust
        let daemon = {
            #[cfg(windows)]
            {
                use tauri::Manager;
                let engine = app
                    .path()
                    .resource_dir()
                    .ok()
                    .map(|r| r.join("engine").join("laris-engine.exe"))
                    .filter(|p| p.exists());
                match engine {
                    Some(bin) => laris::LarisDaemon::with_engine(bin),
                    None => laris::LarisDaemon::new(PathBuf::from(&config.laris_dir)),
                }
            }
            #[cfg(not(windows))]
            {
                laris::LarisDaemon::new(PathBuf::from(&config.laris_dir))
            }
        };
```

(If the setup closure's app handle is named differently, e.g. `app_handle` or
`handle`, use that name. Confirm `tauri::Manager` is imported in that scope or
add the `use` as shown.)

- [ ] **Step 7: Write `apps/tray/src-tauri/tauri.windows.conf.json`**

A Windows-only config overlay merged via `--config` at build time. It bundles
the staged `engine/` folder as an app resource. Keeping it out of the base
`tauri.conf.json` means the macOS/Linux builds never require the folder to exist.

```json
{
  "bundle": {
    "resources": {
      "engine/": "engine/"
    }
  }
}
```

- [ ] **Step 8: Gitignore the staged engine folder**

Append to `apps/tray/src-tauri/.gitignore` (create if absent):
```
# CI stages the frozen engine here before bundling; never committed
engine/
```

- [ ] **Step 9: Confirm the macOS build is unaffected**

Run: `cd apps/tray/src-tauri && cargo test && cargo build`
Expected: green. The `#[cfg(windows)]` block does not compile on macOS; the
overlay JSON is inert until `--config` selects it. Report results.

---

## Task 3: CI builds the frozen engine into the Windows installer

**Owner:** Codex (GitHub Actions). Works only under `.github/`.

**Files:**
- Modify: `.github/workflows/tray-build.yml`

**Interfaces:**
- Consumes: `packages/laris/requirements-windows.txt`, `packages/laris/packaging/laris.spec`
  (Task 1) and the resource path `engine/` in `tauri.windows.conf.json` (Task 2).
- Produces: the Windows `.msi`/`.exe` with the engine bundled.

- [ ] **Step 1: Add a Windows-only engine build before `tauri-action`**

Insert these steps AFTER "Rust tests" and BEFORE the `tauri-apps/tauri-action`
step. They run only on the Windows runner; other platforms skip them and build
the tray without a bundled engine (unchanged).

```yaml
      - name: Set up Python (Windows engine)
        if: matrix.platform == 'windows-latest'
        uses: actions/setup-python@0b93645e9fea7318ecaed2b359559ac225c90a2b # v5
        with:
          python-version: "3.11"

      - name: Build frozen laris engine (Windows)
        if: matrix.platform == 'windows-latest'
        working-directory: packages/laris
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements-windows.txt pyinstaller
          pyinstaller packaging/laris.spec --noconfirm
          # stage the onedir output where tauri.windows.conf.json expects it
          New-Item -ItemType Directory -Force -Path ../../apps/tray/src-tauri/engine | Out-Null
          Copy-Item -Recurse -Force dist/laris-engine/* ../../apps/tray/src-tauri/engine/
        shell: pwsh
```

- [ ] **Step 2: Pass the Windows overlay config to `tauri-action`**

`tauri-action` accepts an `args` input forwarded to `tauri build`. Add a
per-platform arg so only the Windows job merges the engine-resource overlay.
Add to the existing `tauri-apps/tauri-action` step's `with:` block:

```yaml
          args: ${{ matrix.platform == 'windows-latest' && '--config src-tauri/tauri.windows.conf.json' || '' }}
```

- [ ] **Step 3: Sanity-check the workflow YAML**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/tray-build.yml'))"`
Expected: no error (valid YAML). Report the result. (The real proof is a CI run
on a manual `workflow_dispatch`, which the orchestrator triggers after commit -
the executor cannot run GitHub Actions.)

---

## Task 4: Ship and smoke (with the user / on Windows)

Not an executor task - orchestrator + user.

- [ ] Commit Tasks 1-3 (one commit each) and push.
- [ ] Trigger `tray-build.yml` via `workflow_dispatch`; watch the Windows job.
      Iterate on PyInstaller hidden-import / DLL failures until the Windows job
      produces `apps/tray/src-tauri/target/release/bundle/{msi,nsis}/*`.
- [ ] Download the Windows artifact; a friend (or SammyJrDesktop over
      Tailscale/RDP) installs it, grants Microphone under Settings > Privacy,
      holds the activation key, speaks, and confirms text lands in Notepad and
      the orb appears/reacts.
- [ ] Update `docs/INSTALL.md`: add the "CUDA is a manual upgrade" note and the
      first-run model-download expectation.
- [ ] On a green smoke, tag `v0.1.0` to draft the release with all installers.

## Verification

- Task 1: config tests pass, full fast suite green, `laris.spec` compiles, no
  torch/pyobjc/mlx in `requirements-windows.txt`.
- Task 2: `cargo test` (22 tests) + `cargo build` green on macOS; the
  `#[cfg(windows)]` engine-resolution block is present and the overlay JSON is
  valid.
- Task 3: workflow YAML is valid; the Windows job has the engine-build +
  overlay-config steps gated on `windows-latest`.
- Task 4 (gate): the Windows CI job emits an `.msi`/`.exe`; a real Windows smoke
  types dictated text into a focused app with the orb reacting.
