"""Wire-format event pushed from the voice pipeline to the frontend via
/ws/voice - kept separate from state_machine.py since both server.py and
main.py need it without pulling in the full voice pipeline."""
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceEvent:
    phase: str
    amplitude: float
