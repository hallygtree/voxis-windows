import datetime as dt
from pathlib import Path

from miris.config import Config
from miris import vault

NOTES = {
    "categoria": "entrevistas",
    "titulo": "Entrevista Acme: Backend Sênior",
    "resumo": "Conversa técnica sobre a vaga.",
    "action_items": ["Enviar case até sexta"],
}


def _cfg(tmp_path) -> Config:
    return Config(
        vault_root=tmp_path / "vault",
        inbox="inbox",
        llm_command=["true"],
        categories={"entrevistas": "interviews"},
        sessions_dir=tmp_path / "sessions",
    )


def test_slugify_strips_accents_and_symbols():
    assert vault.slugify("Entrevista Acme: Backend Sênior!") == "entrevista-acme-backend-senior"
    assert vault.slugify("!!!") == "reuniao"


def test_save_note_routes_category_to_mapped_folder(tmp_path):
    path = vault.save_note(_cfg(tmp_path), NOTES, "[00:00] Eu: oi", "20260716-1000",
                           date=dt.date(2026, 7, 16))
    assert path == tmp_path / "vault/interviews/2026-07-16-entrevista-acme-backend-senior.md"
    content = path.read_text()
    assert 'categoria: "entrevistas"' in content
    assert "- [ ] Enviar case até sexta" in content
    assert "[00:00] Eu: oi" in content


def test_save_note_unknown_category_goes_to_inbox(tmp_path):
    notes = dict(NOTES, categoria="inventada")
    path = vault.save_note(_cfg(tmp_path), notes, "t", "s", date=dt.date(2026, 7, 16))
    assert path.parent == tmp_path / "vault/inbox"


def test_frontmatter_survives_colon_in_title(tmp_path):
    path = vault.save_note(_cfg(tmp_path), NOTES, "t", "s", date=dt.date(2026, 7, 16))
    frontmatter = path.read_text().split("---")[1]
    assert 'title: "Entrevista Acme: Backend Sênior"' in frontmatter


def test_save_note_avoids_filename_collision(tmp_path):
    cfg = _cfg(tmp_path)
    p1 = vault.save_note(cfg, NOTES, "t", "s1", date=dt.date(2026, 7, 16))
    p2 = vault.save_note(cfg, NOTES, "t", "s2", date=dt.date(2026, 7, 16))
    assert p1 != p2 and p2.name.endswith("-2.md")
