import json
from pathlib import Path

import pytest

from miris.config import Config
from miris import notes

GOOD = {"categoria": "trabalho", "titulo": "T", "resumo": "R", "action_items": ["a"]}


def _cfg(tmp_path, script_body: str) -> Config:
    script = tmp_path / "fake_llm.sh"
    script.write_text(f"#!/bin/sh\n{script_body}\n")
    script.chmod(0o755)
    return Config(vault_root=tmp_path, inbox="inbox", llm_command=[str(script)],
                  categories={"trabalho": "work"}, sessions_dir=tmp_path)


def test_build_prompt_injects_categories():
    prompt = notes.build_prompt(["trabalho", "entrevistas"], "fala")
    assert "trabalho, entrevistas" in prompt
    assert "fala" in prompt


def test_generate_parses_clean_json(tmp_path):
    cfg = _cfg(tmp_path, f"echo '{json.dumps(GOOD)}'")
    assert notes.generate(cfg, "t") == GOOD


def test_generate_strips_markdown_fences(tmp_path):
    cfg = _cfg(tmp_path, f"printf '```json\\n{json.dumps(GOOD)}\\n```\\n'")
    assert notes.generate(cfg, "t") == GOOD


def test_generate_takes_first_json_object_ignoring_trailing_text(tmp_path):
    body = f"echo '{json.dumps(GOOD)}'; echo 'nota: chaves soltas }} aqui {{'"
    cfg = _cfg(tmp_path, body)
    assert notes.generate(cfg, "t") == GOOD


def test_generate_raises_on_missing_binary(tmp_path):
    cfg = _cfg(tmp_path, "true")
    cfg = Config(vault_root=cfg.vault_root, inbox=cfg.inbox,
                 llm_command=[str(tmp_path / "does-not-exist")],
                 categories=cfg.categories, sessions_dir=cfg.sessions_dir)
    with pytest.raises(notes.NotesError):
        notes.generate(cfg, "t")


def test_generate_raises_on_nonzero_exit(tmp_path):
    cfg = _cfg(tmp_path, "exit 3")
    with pytest.raises(notes.NotesError):
        notes.generate(cfg, "t")


def test_generate_raises_on_missing_key(tmp_path):
    cfg = _cfg(tmp_path, "echo '{\"titulo\": \"x\"}'")
    with pytest.raises(notes.NotesError):
        notes.generate(cfg, "t")
