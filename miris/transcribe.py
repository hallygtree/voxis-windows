"""Per-channel STT (mlx-whisper via laris) + timeline merge."""
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

TARGET_SR = 16000


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
        audio = audio.reshape(-1, n_ch).mean(axis=1)
    if sr != TARGET_SR:
        import torch
        import torchaudio.functional as F

        audio = F.resample(torch.from_numpy(audio), sr, TARGET_SR).numpy()
    return audio


def speech_spans(audio: np.ndarray, sr: int = TARGET_SR) -> list[tuple[int, int]]:
    """Silero VAD over the whole file -> utterance-sized (start, end) sample spans."""
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad

    model = load_silero_vad()
    stamps = get_speech_timestamps(torch.from_numpy(audio), model, sampling_rate=sr)
    return [(t["start"], t["end"]) for t in stamps]


def transcribe_channel(path: Path, speaker: str, transcriber,
                       spans_fn=speech_spans) -> list[Segment]:
    audio = load_wav_mono16k(path)
    segments = []
    for start, end in spans_fn(audio):
        text = transcriber.transcribe(audio[start:end])
        if text:
            segments.append(Segment(start / TARGET_SR, end / TARGET_SR, speaker, text))
    return segments


def merge(*channels: list[Segment]) -> str:
    ordered = sorted((s for ch in channels for s in ch), key=lambda s: s.start_s)
    lines = []
    for seg in ordered:
        minutes, seconds = divmod(int(seg.start_s), 60)
        lines.append(f"[{minutes:02d}:{seconds:02d}] {seg.speaker}: {seg.text}")
    return "\n".join(lines)
