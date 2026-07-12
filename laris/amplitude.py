"""Turns a raw audio buffer into the single 0.0-1.0 'energy' value the
voice-reactive widget uses to drive deformation/color/ring speed. RMS is
deliberately the only signal used - amplitude alone is expected to read
as reactive enough; pitch-tracking was considered and explicitly
deferred (see docs/superpowers/specs/2026-07-07-phase2-voice-design.md)."""
import numpy as np

_GAIN = 4.0  # retuned live 2026-07-11: sqrt curve added below, keep gain as-is


def compute_amplitude(audio: np.ndarray) -> float:
    if len(audio) == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(audio))))
    # sqrt lifts conversational volume (RMS ~0.02 -> ~0.28 instead of ~0.08)
    # so the orb visibly tracks speech; loud input still caps at 1.0
    return min(1.0, float(np.sqrt(rms * _GAIN)))
