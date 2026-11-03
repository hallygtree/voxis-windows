import json
import sys
from pathlib import Path

import pytest

from miris.config import Config
from miris import notes

GOOD = {"categoria": "trabalho", "titulo": "T", "resumo": "R", "action_items": ["a"]}


def _fake_llm(tmp_path, body: str) -> list[str]:
    """A stand-in LLM CLI written in Python, not /bin/sh.

    The shell-script fixtures could never run on Windows ("%1 is not a valid
    Win32 application"), so every notes/pipeline test failed here for a reason
    that had nothing to do with the code under test - and the two tests that
    only assert "NotesError is raised" passed for the wrong reason, which is
    worse than failing.
    """
    script = tmp_path / "fake_llm.py"
    script.write_text(body, encoding="utf-8")
    return [sys.executable, str(script)]


def _emit(payload: str) -> str:
    """Body that prints `payload` as UTF-8 regardless of console codepage."""
    return ("import sys\n"
            f"sys.stdout.buffer.write({payload!r}.encode('utf-8'))\n")


def _cfg(tmp_path, script_body: str) -> Config:
    return Config(vault_root=tmp_path, inbox="inbox",
                  llm_command=_fake_llm(tmp_path, script_body),
                  categories={"trabalho": "work"}, sessions_dir=tmp_path)


def test_build_prompt_injects_categories():
    prompt = notes.build_prompt(["trabalho", "entrevistas"], "fala")
    assert "trabalho, entrevistas" in prompt
    assert "fala" in prompt


def test_generate_parses_clean_json(tmp_path):
    cfg = _cfg(tmp_path, _emit(json.dumps(GOOD)))
    assert notes.generate(cfg, "t") == GOOD


def test_generate_strips_markdown_fences(tmp_path):
    cfg = _cfg(tmp_path, _emit(f"```json\n{json.dumps(GOOD)}\n```\n"))
    assert notes.generate(cfg, "t") == GOOD


def test_generate_takes_first_json_object_ignoring_trailing_text(tmp_path):
    cfg = _cfg(tmp_path,
               _emit(f"{json.dumps(GOOD)}\nnota: chaves soltas }} aqui {{\n"))
    assert notes.generate(cfg, "t") == GOOD


def test_generate_decodes_llm_output_as_utf8(tmp_path):
    """The LLM answers in Portuguese. subprocess text=True would decode with
    the locale codepage (cp1252 here) and turn "memória" into "memÃ³ria" -
    and the mangled titulo becomes the note's filename."""
    accented = {**GOOD, "titulo": "Reunião de memória",
                "resumo": "Discussão sobre ações", "action_items": ["Revisão"]}
    cfg = _cfg(tmp_path, _emit(json.dumps(accented, ensure_ascii=False)))
    assert notes.generate(cfg, "t") == accented


def test_generate_raises_on_missing_binary(tmp_path):
    cfg = Config(vault_root=tmp_path, inbox="inbox",
                 llm_command=[str(tmp_path / "does-not-exist")],
                 categories={"trabalho": "work"}, sessions_dir=tmp_path)
    with pytest.raises(notes.NotesError):
        notes.generate(cfg, "t")


def test_generate_raises_on_nonzero_exit(tmp_path):
    cfg = _cfg(tmp_path, "import sys; sys.exit(3)")
    with pytest.raises(notes.NotesError, match="llm exit 3"):
        notes.generate(cfg, "t")


def test_generate_raises_on_missing_key(tmp_path):
    cfg = _cfg(tmp_path, _emit('{"titulo": "x"}'))
    with pytest.raises(notes.NotesError, match="missing key"):
        notes.generate(cfg, "t")
