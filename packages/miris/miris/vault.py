"""Render the meeting note and write it into the vault."""
import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

from miris.config import Config


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len] or "reuniao"


def render_note(notes: dict, transcript: str, session_id: str, date: dt.date) -> str:
    """Full note body: YAML frontmatter + resumo + action items + transcript."""
    items = "\n".join(f"- [ ] {i}" for i in notes.get("action_items", []))
    # json.dumps = valid YAML scalar quoting (titles often contain ":")
    return f"""---
title: {json.dumps(notes['titulo'], ensure_ascii=False)}
date: {date.isoformat()}
categoria: {json.dumps(notes['categoria'], ensure_ascii=False)}
source: miris
session: {json.dumps(session_id)}
---

# {notes['titulo']}

## Resumo

{notes['resumo']}

## Action items

{items}

## Transcript

{transcript}
"""


def _note_path(cfg: Config, categoria: str, titulo: str, date: dt.date) -> Path:
    folder = cfg.categories.get(categoria, cfg.inbox)
    directory = cfg.vault_root / folder
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{date.isoformat()}-{slugify(titulo)}"
    path = directory / f"{base}.md"
    n = 2
    while path.exists():
        path = directory / f"{base}-{n}.md"
        n += 1
    return path


def save_note(cfg: Config, notes: dict, transcript: str, session_id: str,
              date: dt.date | None = None) -> Path:
    date = date or dt.date.today()
    path = _note_path(cfg, notes["categoria"], notes["titulo"], date)
    path.write_text(render_note(notes, transcript, session_id, date), encoding="utf-8")
    return path
