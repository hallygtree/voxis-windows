# Laris.app - microphone TCC wrapper

**Problem:** macOS Terminal/iTerm don't have microphone TCC by default.
Running `python -m laris` from the shell returns silent zeros from the mic
(Whisper hallucinates greetings over silence). Warp Terminal has mic
pre-granted, but friends who download LARIS won't.

**Solution:** `Laris.app` is an AppleScript applet that LaunchServices treats
as a real GUI app. Double-clicking it triggers the macOS mic permission
dialog on first launch. The applet backgrounds the Python daemon and exits;
the daemon inherits the TCC grant.

## Build

```bash
cd ~/code/laris
bash scripts/build-app.sh
```

This recreates `Laris.app/` at the repo root using `osacompile` and injects
`NSMicrophoneUsageDescription` into the Info.plist.

## Use

```bash
open ~/code/laris/Laris.app
```

First launch: macOS shows a mic permission dialog. Grant it.
Subsequent launches: daemon starts silently, logs to `/tmp/laris.log`.

## Stop

```bash
pkill -9 -f "python -m laris"
```
