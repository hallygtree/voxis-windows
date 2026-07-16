"""Summary + classification via the configured LLM CLI (agy by default)."""
import json
import subprocess

from miris.config import Config


class NotesError(Exception):
    pass


PROMPT_TEMPLATE = """Você responde APENAS com JSON válido, sem markdown, sem cercas de código.

Dado o transcript de reunião abaixo, produza exatamente:
{{"categoria": "<uma de: {cats}>", "titulo": "<título curto da reunião>", "resumo": "<resumo em 3-6 frases>", "action_items": ["<item acionável>"]}}

Se nenhuma categoria servir, use "outros".

TRANSCRIPT:
{transcript}
"""


def build_prompt(categories: list[str], transcript: str) -> str:
    return PROMPT_TEMPLATE.format(cats=", ".join(categories), transcript=transcript)


def _extract_json(text: str) -> dict:
    """First balanced JSON object in the output (ignores fences and trailing prose)."""
    start = text.find("{")
    if start < 0:
        raise NotesError(f"no JSON object in LLM output: {text[:200]!r}")
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise NotesError(f"bad JSON from llm: {exc}") from exc
    return obj


def generate(cfg: Config, transcript: str, timeout_s: int = 300) -> dict:
    prompt = build_prompt(list(cfg.categories), transcript)
    try:
        proc = subprocess.run(cfg.llm_command + [prompt], capture_output=True,
                              text=True, timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotesError(f"llm command failed: {exc}") from exc
    if proc.returncode != 0:
        raise NotesError(f"llm exit {proc.returncode}: {proc.stderr[:200]}")
    result = _extract_json(proc.stdout)
    for key in ("categoria", "titulo", "resumo", "action_items"):
        if key not in result:
            raise NotesError(f"missing key {key!r} in llm output")
    return result
