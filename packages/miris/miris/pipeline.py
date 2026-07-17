"""Post-meeting pipeline: WAVs -> transcript -> notes -> vault note."""
import json
import os
from pathlib import Path

from miris import notes as notes_mod
from miris import transcribe, vault
from miris.config import Config

CHANNELS = (("mic.wav", "Eu"), ("system.wav", "Eles"))
WAV_HEADER_BYTES = 44


def _default_transcriber_factory():
    # meetings are bilingual (pt-BR + English): default Whisper to auto-detect
    # per utterance unless the user pinned STT_LANGUAGE themselves
    os.environ.setdefault("STT_LANGUAGE", "")
    from laris.transcriber import Transcriber
    return Transcriber()


def build_transcript(session_dir: Path, transcriber_factory=None) -> str:
    """Transcribe every readable channel and merge into one timeline."""
    factory = transcriber_factory or _default_transcriber_factory
    transcriber = factory()
    if hasattr(transcriber, "warm"):
        transcriber.warm()
    # NOTE: keep this sequential. mlx-whisper is not safe to call concurrently
    # from multiple threads sharing one model - parallelizing the two channels
    # to halve latency would need one Transcriber (Metal context) per thread.
    channels = []
    for wav_name, speaker in CHANNELS:
        path = session_dir / wav_name
        if path.exists() and path.stat().st_size > WAV_HEADER_BYTES:
            try:
                channels.append(transcribe.transcribe_channel(
                    path, speaker, transcriber, transcribe.speech_spans))
            except Exception as exc:  # helper killed mid-meeting leaves a broken WAV
                print(f"[transcribe] {wav_name} unreadable ({exc}) - continuing without it")
    return transcribe.merge(*channels)


def process_session(cfg: Config, session_dir: Path, transcriber_factory=None) -> Path:
    """Session dir -> saved vault note path. Transcript is cached; LLM failure
    still produces a transcript-only note routed to the inbox."""
    transcript_path = session_dir / "transcript.md"
    if transcript_path.exists():
        transcript = transcript_path.read_text(encoding="utf-8")
    else:
        transcript = build_transcript(session_dir, transcriber_factory)
        transcript_path.write_text(transcript, encoding="utf-8")

    try:
        notes = notes_mod.generate(cfg, transcript)
    except notes_mod.NotesError as exc:
        print(f"[notes] failed: {exc} - saving transcript-only note to inbox; "
              f"run `miris retry {session_dir.name}` to regenerate")
        notes = {
            "categoria": "__falha__",
            "titulo": f"Reunião {session_dir.name}",
            "resumo": f"(resumo indisponível: {exc})",
            "action_items": [],
        }
    (session_dir / "notes.json").write_text(
        json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    note = vault.save_note(cfg, notes, transcript, session_dir.name)
    # the VOXIS tray reads this to open the last note without parsing CLI stdout
    (session_dir / "note.path").write_text(str(note), encoding="utf-8")
    return note
