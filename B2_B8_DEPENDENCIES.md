# B2-B8 Dependencies Report (Post-B1 Implementation)

## Status After B1 Completion

B1 (WASAPI loopback audio capture) is **structurally complete** and ready for Windows validation via `voxis-verify-windows`.

### B1 Summary
- ✅ `WindowsLoopbackTap` in `packages/miris/miris/loopback_windows.py`
- ✅ `Tap` interface in `packages/miris/miris/systemtap.py`
- ✅ `default_tap_factory()` platform-aware factory
- ✅ Updated `recorder.py` to use factory
- ✅ Updated `cli.py::cmd_doctor()` for platform-aware testing
- ✅ `requirements-windows.txt` torch-free dependencies
- ✅ Unit tests in `test_loopback_windows.py`

## Next Priorities (Parallel-able Tasks)

### B2: Parada via Arquivo-Sentinela (Already Partially Implemented)
**Status**: ~60% done in `recorder.py` and `cli.py`
- ✅ `recorder.py::main()` polls `stop` sentinel file (line 88-93)
- ✅ `cli.py::cmd_stop()` creates sentinel file (line 76-79)
- **Remaining**: Validate that sentinel polling doesn't race with SIGTERM on cross-platform scenarios

**Owner**: miris-windows-dev
**Files**:
- `packages/miris/miris/recorder.py` (already updated)
- `packages/miris/miris/cli.py` (already updated)
- Tests: `packages/miris/tests/test_cli.py`

**Criterion**: `miris stop` on Windows creates `<session>/stop` file; recorder exits cleanly without SIGTERM

---

### B3: VAD Embutido do Faster-Whisper (Partially Seen)
**Status**: Changes visible in `transcribe.py` (line count increased from 57 to 75 lines)
- **Likely changes**: Replace `silero_vad.load_model()` / speech spans with `faster-whisper` VAD
- **Impact**: Granularity of `Segment` / timeline in `merge()` may change

**Owner**: miris-windows-dev
**Files**:
- `packages/miris/miris/transcribe.py` (check `load_wav_mono16k`, `speech_spans`)
- `packages/miris/miris/pipeline.py` (check `merge()` function)
- Tests: `packages/miris/tests/test_transcribe.py`

**Criterion**: 
- `transcribe.py` uses `faster_whisper.load_model().transcribe(...).language_probability` or equivalent VAD
- No `silero_vad` import
- No `torch` / `torchaudio` in runtime path
- Timeline merge handles variable segment granularity

**Validation**: Transcribe sample pt-BR + English audio; verify segment boundaries align with faster-whisper VAD (not silero)

---

### B4: Transcriber Default = FasterWhisperTranscriber
**Status**: Changes visible in `pipeline.py` (~11 lines added)
- **Likely changes**: `_default_transcriber_factory()` returns `laris.stt_faster.FasterWhisperTranscriber` on Windows instead of mlx
- **Interface**: Must match existing `.transcribe()` / `.warm()` signatures

**Owner**: miris-windows-dev
**Files**:
- `packages/miris/miris/pipeline.py` (check `_default_transcriber_factory()`)
- `packages/miris/requirements-windows.txt` (ensure `laris` is included)
- Tests: `packages/miris/tests/test_pipeline.py`

**Criterion**:
- Windows uses `FasterWhisperTranscriber` (via `laris.stt_faster`)
- macOS can still use mlx via default factory
- No `torch` / `mlx` in Windows runtime

**Validation**: `miris doctor` completes transcription test; output matches expected format

---

### B5: PID Alive Detection (Tray-Dev Responsibility)
**Status**: Blocked on `tray-dev` (Rust side)
- **Issue**: `pid_alive()` in `apps/tray/src-tauri/src/miris.rs` returns false on Windows
- **Root cause**: Can't reliably check process alive status in frozen Python on Windows

**Owner**: tray-dev (Rust)
**Mitigation**: You document the contract in `apps/tray/src-tauri/src/miris.rs`:
- Input: recorder PID + session dir path
- Output: true if recorder process is alive (check via Windows process handles, not SIGTERM)
- Fallback: Return `(session_dir / "recorder.pid").exists()` if process handle unavailable

**Action for miris-windows-dev**: 
- Ensure `recorder.pid` is always written immediately in `recorder.py::main()` ✅ (already done)
- Document contract in README / spec

---

### B6: Miris Binary Path Resolution (Tray-Dev Responsibility)
**Status**: Blocked on `tray-dev` (Rust side)
- **Issue**: `miris_bin` points to `~/.local/bin/miris` (doesn't exist without Python venv)

**Owner**: tray-dev (Rust)
**Mitigation**: Resolve path in `apps/tray/src-tauri/src/settings.rs`:
- Windows frozen: Look for `miris-engine.exe` in:
  1. Same dir as tray executable
  2. `../engine-miris/` relative to tray
  3. PATH search via `shutil.which` equivalent (Rust: `which` crate)
- macOS: Keep existing `~/.local/bin/miris` path

**Action for miris-windows-dev**:
- Ensure frozen executable is named `miris-engine.exe` and placed in expected location ✅
- Document contract in spec

---

### B7: Spawn Detach / -m miris.recorder (Already Partially Implemented)
**Status**: ~90% done in `cli.py::cmd_start()`
- ✅ Windows frozen: uses `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` flags (line 51)
- ✅ Windows frozen: references `__recorder` subcommand (line 49)
- ✅ macOS: still uses `start_new_session=True`
- **Remaining**: Implement `__recorder` internal subcommand in frozen executable entry point

**Owner**: miris-windows-dev (in combination with packaging/PyInstaller spec)
**Files**:
- `packages/miris/miris/cli.py` (already updated)
- `packages/miris/packaging/entry.py` (NEW: main entry point for frozen exe) - see notes below
- `packages/miris/packaging/miris.spec` (PyInstaller spec) - see notes below

**Criterion**:
- `miris-engine.exe start` spawns detached recorder on Windows without console window
- Recorder process survives tray close
- Tests: `packages/miris/tests/test_cli.py::test_cmd_start_frozen`

**Notes on Implementation**:
```python
# packages/miris/packaging/entry.py (pseudocode)
def main():
    if sys.argv[1] == "__recorder":
        # Internal subcommand for frozen executable
        from miris.recorder import main as recorder_main
        sys.argv = [sys.argv[0]] + sys.argv[2:]  # Remove __recorder from argv
        recorder_main()
    else:
        # Standard CLI dispatch
        from miris.cli import main
        main()
```

---

### B8: Resolve llm_command via shutil.which (Already Done)
**Status**: ✅ **COMPLETE** - see `cli.py::cmd_doctor()` lines 135-139
- ✅ Uses `shutil.which(llm_cmd[0])` to resolve `.cmd`/`.exe` shims on Windows
- ✅ Fallback to original if not found

**Owner**: miris-windows-dev
**Validation**: `miris doctor` successfully resolves and runs LLM command on Windows

---

## Packaging Notes (SDD-B2..B8)

A `packages/miris/packaging/` directory should be created to hold:

1. **miris.spec** (PyInstaller configuration)
   ```
   - Includes miris package + laris (torch-free)
   - Excludes: torch, torchaudio, silero-vad, mlx, pyobjc
   - Collects: soundcard DLLs, onnxruntime binaries
   - Entry: packages/miris/packaging/entry.py::main
   - Output: miris-engine.exe (onedir or onefile)
   ```

2. **entry.py** (Frozen executable entry point)
   ```
   - Dispatches __recorder internal subcommand (B7)
   - Falls back to cli.main() for normal commands
   - Handles Windows-specific detach via creationflags
   ```

3. **requirements-windows.txt** ✅ (Already created)
   - numpy, sounddevice, soundcard, faster-whisper, laris
   - No torch/torchaudio/silero/mlx

---

## Risk Log (Open Items)

| Risk | Mitigation | Owner |
|------|-----------|-------|
| Loopback device unavailable | Graceful degradation with warning | miris-windows-dev |
| Device format not 48kHz | Normalize in `_resample_poly()` | miris-windows-dev |
| PyInstaller missing DLLs | `collect_all("soundcard")` in spec | miris-windows-dev |
| B3 VAD granularity breaks timeline | Test with actual pt-BR/EN audio | miris-windows-dev |
| B5/B6 process detection race | Document contract, handle None gracefully | tray-dev + miris-windows-dev |

---

## Next Immediate Actions

1. **Validate B1** via `voxis-verify-windows` (real audio capture test)
2. **Review B3** in `transcribe.py` (VAD switch) and test timeline merge
3. **Review B4** in `pipeline.py` (transcriber default) and validate interface
4. **Implement B7** entry.py + miris.spec for packaging
5. **Coordinate B5/B6** with tray-dev on process/binary resolution

---

## File Inventory (Post-B1)

**Created**:
- ✅ `packages/miris/miris/loopback_windows.py` (WindowsLoopbackTap)
- ✅ `packages/miris/requirements-windows.txt`
- ✅ `packages/miris/tests/test_loopback_windows.py`
- ❌ `packages/miris/packaging/` (not yet created - B7/B2)

**Modified**:
- ✅ `packages/miris/miris/systemtap.py` (Tap interface, default_tap_factory)
- ✅ `packages/miris/miris/recorder.py` (Tap + factory, sentinel polling)
- ✅ `packages/miris/miris/cli.py` (platform-aware doctor, frozen detach, sentinel stop, shutil.which)
- 🔄 `packages/miris/miris/transcribe.py` (likely B3 changes - review)
- 🔄 `packages/miris/miris/pipeline.py` (likely B4 changes - review)
- 🔄 `packages/miris/miris/notes.py` (likely B8 changes - review)
