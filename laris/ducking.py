"""Duck system output volume while the user talks to the assistant.

Music/Discord bleeding into the mic degrades transcription; lowering the
MASTER output during capture is the whole fix - per-app volumes don't
exist on macOS without an audio driver. Known ceiling: if the user
changes volume manually while ducked, restore() overwrites it.
"""
from __future__ import annotations

import subprocess

# same rationale as dictation.py: a hung osascript must not freeze the loop
_SUBPROCESS_TIMEOUT_SECONDS = 4
DUCK_VOLUME = 20


class AudioDucker:
    def __init__(self) -> None:
        self._saved: int | None = None

    def duck(self) -> None:
        if self._saved is not None:
            return  # already ducked (hands-free session + PTT overlap)
        try:
            result = subprocess.run(
                ["osascript", "-e", "output volume of (get volume settings)"],
                capture_output=True,
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
            current = int(result.stdout.strip())
        except Exception:  # noqa: BLE001 - ducking is best-effort
            return
        if current <= DUCK_VOLUME:
            return
        try:
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {DUCK_VOLUME}"],
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
            self._saved = current
        except Exception:  # noqa: BLE001
            pass

    def restore(self) -> None:
        if self._saved is None:
            return
        saved, self._saved = self._saved, None
        try:
            subprocess.run(
                ["osascript", "-e", f"set volume output volume {saved}"],
                timeout=_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except Exception:  # noqa: BLE001
            pass
