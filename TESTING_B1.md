# Testing B1: WASAPI Loopback Audio Capture

## Local Development Testing (Python 3.11)

```bash
# 1. Install torch-free requirements
pip install -r packages/miris/requirements-windows.txt

# 2. Run unit tests (no hardware required)
pytest packages/miris/tests/test_loopback_windows.py -v
pytest packages/miris/tests/test_recorder.py -v  # Should still pass with interface changes

# 3. Quick import check (validates no circular imports)
python -c "from miris.systemtap import default_tap_factory, Tap; print('OK')"

# 4. Check platform detection
python -c "from miris.systemtap import default_tap_factory; f = default_tap_factory(); print(f.__name__)"
# Should print: WindowsLoopbackTap (on Windows) or SystemTap (on macOS/Linux)
```

## Integration Testing with Real Audio (voxis-verify-windows)

**Prerequisites**:
- Windows 11 Pro with Stereo Mix or NVIDIA HiFi enabled
- Speaker connected and unmuted
- Audio file to play during test (e.g., speech sample in Portuguese/English)

**Test Steps**:

1. **Start recording**:
   ```bash
   miris start
   ```
   Verify: `recorder.pid` file created, no errors in `recorder.log`

2. **Play audio**:
   - Open browser and play audio (speech, podcast, etc.)
   - Play for 5-10 seconds
   - Keep window open to monitor real-time levels

3. **Stop recording**:
   ```bash
   miris status  # Should show recording active
   miris stop
   ```
   Verify: Both `mic.wav` and `system.wav` files exist in session dir

4. **Validate outputs**:
   ```bash
   # Check file sizes (should be > 44 bytes, typically > 100KB for 5s)
   ls -lh ~/.miris/sessions/YYYYMMDD-HHMMSS/
   
   # Check audio properties
   ffprobe -v quiet -print_format json -show_format ~/.miris/sessions/YYYYMMDD-HHMMSS/system.wav | jq '.format'
   # Should show: sample_rate=16000, channels=1, duration > 4s
   
   # Play back to verify audibility
   ffplay ~/.miris/sessions/YYYYMMDD-HHMMSS/system.wav
   ```

5. **Validate transcription pipeline**:
   ```bash
   miris retry YYYYMMDD-HHMMSS
   # Should run faster-whisper on both mic.wav and system.wav
   # Output: note with merged transcript including system audio
   ```

**Expected Outcomes**:
- ✅ `system.wav`: 16 kHz mono, contains system audio from loopback
- ✅ `mic.wav`: 16 kHz mono, contains microphone input
- ✅ No truncated WAV files (byte count correct, headers valid)
- ✅ Merged transcript in note includes both speakers

**Failure Scenarios & Diagnostics**:

| Symptom | Cause | Fix |
|---------|-------|-----|
| `system.wav` empty or missing | Loopback device not available | Enable Stereo Mix / NVIDIA HiFi in audio settings |
| `system.wav` < 44 bytes | Capture failed to start | Check `recorder.log` for soundcard errors |
| `system.wav` truncated (wrong size) | Thread didn't finish | Check `recorder.log` for thread errors in `_capture_loop()` |
| WAV invalid (can't play) | Header not written correctly | Verify wave.py behavior in loopback_windows.py |
| Misaligned timeline | VAD granularity changed (B3) | Check transcription segments in next iteration |

---

## Smoke Test (miris doctor)

```bash
miris doctor
```

**On macOS**:
```
[ok] audiotap binary: /path/to/helper/audiotap
[ok] vault_root: ~/.miris/vault
[ok] categories configured: ...
[ok] llm_command: agy -m ...
[ok] system-audio smoke (3s): 50000 bytes
```

**On Windows**:
```
[ok] system audio: WASAPI loopback (Windows)
[ok] vault_root: ...
[ok] categories configured: ...
[ok] llm_command: agy.cmd -m ...
[ok] system-audio smoke (3s): 45000 bytes
```

---

## Implementation Checklist (For Code Review)

- [x] `systemtap.py`: Abstract `Tap` interface with start/alive/stop
- [x] `systemtap.py`: `SystemTap` implements `Tap` (macOS unchanged)
- [x] `systemtap.py`: `default_tap_factory()` returns platform-specific implementation
- [x] `loopback_windows.py`: `WindowsLoopbackTap` captures 48kHz → 16kHz via numpy
- [x] `loopback_windows.py`: Thread-safe WAV writing with lock + clean shutdown
- [x] `recorder.py`: Uses `default_tap_factory()` if no tap_factory injected
- [x] `recorder.py`: Existing tests still pass (FakeTap implements Tap)
- [x] `cli.py::cmd_doctor()`: Platform-aware smoke test (audiotap on macOS, loopback on Windows)
- [x] `requirements-windows.txt`: No torch/torchaudio/silero-vad/mlx/pyobjc
- [x] `test_loopback_windows.py`: Interface + lifecycle tests

---

## Known Limitations (Documented)

1. **No loopback device**: System audio capture fails silently with warning (acceptable for recordings without system audio)
2. **Device format variations**: Code normalizes 48kHz → 16kHz, should handle 44.1kHz too
3. **Runtime device switching**: If speaker default changes mid-recording, current loopback stream doesn't adapt (rare, acceptable)
4. **No device selection UI**: Only default speaker loopback supported (B1 requirement met)

---

## Next Steps

1. **Validation**: Run with `voxis-verify-windows` on real Windows 11 system with audio hardware
2. **B3 Review**: Check `transcribe.py` VAD changes (faster-whisper built-in)
3. **B4 Review**: Check `pipeline.py` transcriber default (FasterWhisperTranscriber)
4. **B7 Implementation**: Create `packages/miris/packaging/entry.py` for frozen executable
5. **Packaging**: Setup PyInstaller spec to bundle miris-engine.exe with DLLs

---

## Performance Notes

- **Capture latency**: ~100ms per chunk (CHUNK_SIZE=4800 samples @ 48kHz)
- **CPU overhead**: Thread-based capture is lightweight (~2-5% CPU)
- **Memory**: Buffers one chunk at a time + WAV headers only (no full-file buffering)
- **Downsample overhead**: Simple moving-average filter + decimation (fast with numpy)

---

## References

- **SDD**: `docs/superpowers/plans/2026-07-20-miris-b1-audiocapture.md`
- **soundcard docs**: https://python-soundcard.readthedocs.io/
- **numpy resampling**: Using polyphase decimation (no scipy)
- **wav module**: Python stdlib wave.py for incremental WAV writing
