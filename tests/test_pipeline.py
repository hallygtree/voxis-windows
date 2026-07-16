import json
import wave

import numpy as np

from miris.config import Config
from miris import pipeline


def _cfg(tmp_path, llm_body: str) -> Config:
    script = tmp_path / "llm.sh"
    script.write_text(f"#!/bin/sh\n{llm_body}\n")
    script.chmod(0o755)
    return Config(vault_root=tmp_path / "vault", inbox="inbox",
                  llm_command=[str(script)],
                  categories={"trabalho": "work"},
                  sessions_dir=tmp_path / "sessions")


def _session_with_mic(tmp_path):
    session = tmp_path / "sessions" / "20260716-1000"
    session.mkdir(parents=True)
    with wave.open(str(session / "mic.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(np.zeros(16000, dtype=np.int16).tobytes())
    return session


class FakeTranscriber:
    def warm(self):
        pass

    def transcribe(self, audio):
        return "fala"


def test_process_session_happy_path(tmp_path, monkeypatch):
    good = json.dumps({"categoria": "trabalho", "titulo": "Sync",
                       "resumo": "R", "action_items": []})
    cfg = _cfg(tmp_path, f"echo '{good}'")
    session = _session_with_mic(tmp_path)
    monkeypatch.setattr("miris.transcribe.speech_spans",
                        lambda a, sr=16000: [(0, 16000)])
    note = pipeline.process_session(cfg, session, transcriber_factory=FakeTranscriber)
    assert note.parent == tmp_path / "vault/work"
    assert "fala" in note.read_text()
    assert (session / "transcript.md").exists()
    assert (session / "notes.json").exists()


def test_process_session_llm_failure_goes_to_inbox(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path, "exit 1")
    session = _session_with_mic(tmp_path)
    monkeypatch.setattr("miris.transcribe.speech_spans",
                        lambda a, sr=16000: [(0, 16000)])
    note = pipeline.process_session(cfg, session, transcriber_factory=FakeTranscriber)
    assert note.parent == tmp_path / "vault/inbox"
    assert "resumo indisponível" in note.read_text()


def test_process_session_reuses_cached_transcript(tmp_path):
    good = json.dumps({"categoria": "trabalho", "titulo": "Sync",
                       "resumo": "R", "action_items": []})
    cfg = _cfg(tmp_path, f"echo '{good}'")
    session = _session_with_mic(tmp_path)
    (session / "transcript.md").write_text("[00:00] Eu: cached")

    def boom():
        raise AssertionError("must not transcribe when cached")

    note = pipeline.process_session(cfg, session, transcriber_factory=boom)
    assert "cached" in note.read_text()
