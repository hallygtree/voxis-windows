"""Per-channel STT (mlx-whisper via laris) + timeline merge."""
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
    # B3: this used to resample via torchaudio, which is not in the torch-free
    # Windows bundle. Windows capture already writes 16 kHz mono, so that path
    # never runs there - but the macOS helper writes at the device's native
    # rate (audiotap.swift takes mSampleRate from the tap format, typically
    # 48 kHz stereo), so dropping resampling outright would have made every
    # macOS meeting silently lose its system channel: build_transcript()
    # swallows per-channel errors and carries on with the other one.
    return resample_to_16k(audio, sr)


def speech_spans(audio: np.ndarray, sr: int = TARGET_SR) -> list[tuple[int, int]]:
    """Silero VAD over the whole file -> utterance-sized (start, end) sample spans."""
    import torch
    from silero_vad import get_speech_timestamps, load_silero_vad

    model = load_silero_vad()
    stamps = get_speech_timestamps(torch.from_numpy(audio), model, sampling_rate=sr)
    return [(t["start"], t["end"]) for t in stamps]


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


def transcribe_channel(path: Path, speaker: str, transcriber,
                       spans_fn=speech_spans) -> list[Segment]:
    audio = load_wav_mono16k(path)
    segments = []

    # If transcriber supports VAD-aware transcription (whisper.cpp), use it
    if hasattr(transcriber, "transcribe_with_vad"):
        # Returns segments carrying start/end timestamps on the original
        # timeline, so no offset arithmetic is needed here
        for segment in transcriber.transcribe_with_vad(audio):
            text = collapse_repetitions(segment.text)
            if text:
                segments.append(Segment(segment.start, segment.end, speaker, text))
    else:
        # Fallback: use speech_spans for VAD (legacy path for mlx)
        for start, end in spans_fn(audio):
            text = collapse_repetitions(transcriber.transcribe(audio[start:end]))
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
