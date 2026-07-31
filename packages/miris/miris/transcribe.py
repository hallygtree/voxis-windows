"""Per-channel STT (whisper.cpp via laris) + timeline merge."""
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from miris.audio import TARGET_SR, downmix_to_mono, resample_to_16k


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    speaker: str
    text: str


def load_wav_mono16k(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        sr = w.getframerate()
        n_ch = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    else:
        raise ValueError(f"unsupported sample width {width} in {path}")
    if n_ch > 1:
        audio = audio[: len(audio) - len(audio) % n_ch]  # tolerate truncated WAVs
        audio = downmix_to_mono(audio.reshape(-1, n_ch))
    # Capture already writes 16 kHz mono, so this is normally a no-op - but a
    # device that reports another rate would otherwise be transcribed at the
    # wrong speed, and build_transcript swallows per-channel errors, so it
    # would surface as a meeting quietly missing one side.
    return resample_to_16k(audio, sr)


def collapse_repetitions(text: str, max_run: int = 3) -> str:
    """Cap consecutive repeated words - Whisper's hallucination mode on noisy
    or overlapping audio repeats one token hundreds of times."""
    out: list[str] = []
    run = 0
    for word in text.split():
        if out and word.casefold() == out[-1].casefold():
            run += 1
            if run >= max_run:
                continue
        else:
            run = 0
        out.append(word)
    return " ".join(out)


def transcribe_channel(path: Path, speaker: str, transcriber) -> list[Segment]:
    """Segments carry start/end on the original timeline, so no offset
    arithmetic is needed here.

    There used to be a fallback that ran a torch VAD and transcribed each span
    separately, for transcribers without transcribe_with_vad. That was the mlx
    path; the only transcriber left has the method, and silently producing a
    worse transcript would be harder to notice than failing."""
    audio = load_wav_mono16k(path)
    segments = []
    for segment in transcriber.transcribe_with_vad(audio):
        text = collapse_repetitions(segment.text)
        if text:
            segments.append(Segment(segment.start, segment.end, speaker, text))
    return segments


def merge(*channels: list[Segment]) -> str:
    ordered = sorted((s for ch in channels for s in ch), key=lambda s: s.start_s)
    lines = []
    for seg in ordered:
        minutes, seconds = divmod(int(seg.start_s), 60)
        lines.append(f"[{minutes:02d}:{seconds:02d}] {seg.speaker}: {seg.text}")
    return "\n".join(lines)
