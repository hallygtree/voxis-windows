import json
import sys
import wave

import numpy as np

from miris.config import Config
from miris import pipeline


def _cfg(tmp_path, llm_body: str) -> Config:
    # Python, not /bin/sh: a shell script is not executable on Windows
    # ("%1 is not a valid Win32 application") and the failure looked like a
    # pipeline bug rather than a broken fixture.
    script = tmp_path / "llm.py"
    script.write_text(llm_body, encoding="utf-8")
    return Config(vault_root=tmp_path / "vault", inbox="inbox",
                  llm_command=[sys.executable, str(script)],
                  categories={"trabalho": "work"},
                  sessions_dir=tmp_path / "sessions")


def _emit(payload: str) -> str:
    return ("import sys\n"
            f"sys.stdout.buffer.write({payload!r}.encode('utf-8'))\n")


def _session_with_mic(tmp_path):
    session = tmp_path / "sessions" / "20260716-1000"
    session.mkdir(parents=True)
    with wave.open(str(session / "mic.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(np.zeros(16000, dtype=np.int16).tobytes())
    return session


class _Segment:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class FakeTranscriber:
    """transcribe_with_vad is the whole contract now - transcribe_channel has
    no fallback for a transcriber without it."""

    def warm(self):
        pass

    def transcribe_with_vad(self, audio, sample_rate=16000):
        return [_Segment(0.0, 1.0, "fala")]


def test_process_session_happy_path(tmp_path, monkeypatch):
    good = json.dumps({"categoria": "trabalho", "titulo": "Sync",
                       "resumo": "R", "action_items": []})
    cfg = _cfg(tmp_path, _emit(good))
    session = _session_with_mic(tmp_path)
    note = pipeline.process_session(cfg, session, transcriber_factory=FakeTranscriber)
    assert note.parent == tmp_path / "vault/work"
    assert "fala" in note.read_text(encoding="utf-8")
    assert (session / "transcript.md").exists()
    assert (session / "notes.json").exists()


def test_process_session_records_note_path(tmp_path, monkeypatch):
    good = json.dumps({"categoria": "trabalho", "titulo": "Sync",
                       "resumo": "R", "action_items": []})
    cfg = _cfg(tmp_path, _emit(good))
    session = _session_with_mic(tmp_path)
    note = pipeline.process_session(cfg, session, transcriber_factory=FakeTranscriber)
    assert (session / "note.path").read_text(encoding="utf-8") == str(note)


def test_process_session_llm_failure_goes_to_inbox(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, "import sys; sys.exit(1)")
    session = _session_with_mic(tmp_path)
    note = pipeline.process_session(cfg, session, transcriber_factory=FakeTranscriber)
    assert note.parent == tmp_path / "vault/inbox"
    assert "resumo indisponível" in note.read_text(encoding="utf-8")


def test_process_session_reuses_cached_transcript(tmp_path):
    good = json.dumps({"categoria": "trabalho", "titulo": "Sync",
                       "resumo": "R", "action_items": []})
    cfg = _cfg(tmp_path, _emit(good))
    session = _session_with_mic(tmp_path)
    (session / "transcript.md").write_text("[00:00] Eu: cached", encoding="utf-8")

    def boom():
        raise AssertionError("must not transcribe when cached")

    note = pipeline.process_session(cfg, session, transcriber_factory=boom)
    assert "cached" in note.read_text(encoding="utf-8")
