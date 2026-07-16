# MIRIS Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local Krisp-style meeting recorder: `miris start/stop` records mic + system audio, transcribes locally (mlx-whisper via laris), summarizes/classifies via `agy -p` (Gemini), saves the note into the Obsidian vault folder mapped to the category.

**Architecture:** Sibling package at `~/code/miris` depending on `laris` as an editable lib. A detached recorder process writes `mic.wav` (sounddevice) and `system.wav` (Swift Core Audio tap helper) until SIGTERM. `miris stop` then runs the pipeline: VAD-chunked per-channel STT → timestamp-merged "Eu/Eles" transcript → LLM notes JSON → vault markdown note. Classification failures land in the vault inbox; `miris retry` reprocesses.

**Tech Stack:** Python 3.11+ (stdlib `wave`, `tomllib`, `argparse`), numpy, sounddevice, silero-vad + torch/torchaudio + mlx-whisper (all via laris), Swift helper (CoreAudio/AudioToolbox, macOS 14.2+), `agy` CLI.

## Global Constraints

- Python `>=3.11` (tomllib); macOS 14.2+ (Core Audio process tap API); Apple Silicon (mlx-whisper).
- All code, comments, commit messages in English. STT output and note content are pt-BR.
- No new Python dependencies beyond: `numpy`, `sounddevice`, `laris` (editable, pulls torch/torchaudio/silero-vad/mlx-whisper). Tests: `pytest`.
- Tests must run without audio hardware, network, or the `agy` binary — inject fakes.
- Config lives at `~/.miris/config.toml`; `MIRIS_HOME` env var overrides `~/.miris` (tests use it).
- `llm_command` default (verbatim): `["agy", "--model", "Gemini 3.5 Flash (Medium)", "-p"]`.
- The spec is at `docs/superpowers/specs/2026-07-16-miris-core-design.md`. Deviation from spec: pipeline orchestration lives in `miris/pipeline.py` (not inside `cli.py`) for testability; `cli.py` stays a thin argparse dispatcher.

---

### Task 1: Package scaffold + config

**Files:**
- Create: `pyproject.toml`, `requirements.txt`, `.gitignore`, `miris/__init__.py`, `miris/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `miris.config.Config` frozen dataclass with fields `vault_root: Path`, `inbox: str`, `llm_command: list[str]`, `categories: dict[str, str]`, `sessions_dir: Path`; `miris.config.load(path: Path | None = None) -> Config`; `miris.config.miris_home() -> Path` (respects `MIRIS_HOME` env var). Later tasks construct `Config(...)` directly in tests.

- [ ] **Step 1: Scaffold package files**

`pyproject.toml`:
```toml
[project]
name = "miris"
version = "0.1.0"
description = "Meeting Intelligence Recording & Insight System"
requires-python = ">=3.11"
dependencies = ["numpy>=1.24.0", "sounddevice>=0.4.6", "laris"]

[project.scripts]
miris = "miris.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["miris*"]
```

`requirements.txt`:
```
-e ../laris
-e .
pytest>=8.0.0
```

`.gitignore`:
```
.venv/
__pycache__/
*.egg-info/
helper/audiotap
```

`miris/__init__.py`: empty file.

- [ ] **Step 2: Write the failing test**

`tests/test_config.py`:
```python
import textwrap
from pathlib import Path

from miris import config


def test_load_creates_default_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRIS_HOME", str(tmp_path))
    cfg = config.load()
    assert (tmp_path / "config.toml").exists()
    assert cfg.vault_root == Path("~/vault").expanduser()
    assert cfg.inbox == "inbox"
    assert cfg.llm_command[0] == "agy"
    assert cfg.sessions_dir == tmp_path / "sessions"


def test_load_parses_user_config(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRIS_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text(textwrap.dedent("""\
        vault_root = "/tmp/vault"
        inbox = "caixa"
        llm_command = ["claude", "-p"]
        [categories]
        entrevistas = "interviews"
    """))
    cfg = config.load()
    assert cfg.vault_root == Path("/tmp/vault")
    assert cfg.inbox == "caixa"
    assert cfg.llm_command == ["claude", "-p"]
    assert cfg.categories == {"entrevistas": "interviews"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd ~/code/miris && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pytest tests/test_config.py -v`
Expected: FAIL (ImportError / AttributeError: module 'miris.config' not found).

- [ ] **Step 4: Implement `miris/config.py`**

```python
"""Config: ~/.miris/config.toml - categories -> vault folders, llm command, paths."""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TOML = """\
vault_root = "~/vault"
inbox = "inbox"
# swapping provider = edit this line, never code (Google killed gemini-cli logins mid-2026)
llm_command = ["agy", "--model", "Gemini 3.5 Flash (Medium)", "-p"]

[categories]
# category -> vault-relative folder; edit to taste
trabalho = "work/meetings"
minhas-empresas = "own/meetings"
entrevistas = "interviews"
"""


def miris_home() -> Path:
    return Path(os.environ.get("MIRIS_HOME", "~/.miris")).expanduser()


@dataclass(frozen=True)
class Config:
    vault_root: Path
    inbox: str
    llm_command: list[str]
    categories: dict[str, str]
    sessions_dir: Path


def load(path: Path | None = None) -> Config:
    home = miris_home()
    path = path or home / "config.toml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_TOML)
    data = tomllib.loads(path.read_text())
    return Config(
        vault_root=Path(data["vault_root"]).expanduser(),
        inbox=data.get("inbox", "inbox"),
        llm_command=list(data["llm_command"]),
        categories=dict(data.get("categories", {})),
        sessions_dir=home / "sessions",
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml requirements.txt .gitignore miris/ tests/
git commit -m "feat: package scaffold and TOML config"
```

---

### Task 2: Vault note rendering and routing

**Files:**
- Create: `miris/vault.py`
- Test: `tests/test_vault.py`

**Interfaces:**
- Consumes: `miris.config.Config`.
- Produces: `slugify(text: str, max_len: int = 60) -> str`; `render_note(notes: dict, transcript: str, session_id: str, date: datetime.date) -> str`; `save_note(cfg: Config, notes: dict, transcript: str, session_id: str, date: datetime.date | None = None) -> Path`. `notes` dict keys: `categoria`, `titulo`, `resumo`, `action_items` (list[str]). Unknown `categoria` routes to `cfg.inbox`.

- [ ] **Step 1: Write the failing test**

`tests/test_vault.py`:
```python
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
    assert "categoria: entrevistas" in content
    assert "- [ ] Enviar case até sexta" in content
    assert "[00:00] Eu: oi" in content


def test_save_note_unknown_category_goes_to_inbox(tmp_path):
    notes = dict(NOTES, categoria="inventada")
    path = vault.save_note(_cfg(tmp_path), notes, "t", "s", date=dt.date(2026, 7, 16))
    assert path.parent == tmp_path / "vault/inbox"


def test_save_note_avoids_filename_collision(tmp_path):
    cfg = _cfg(tmp_path)
    p1 = vault.save_note(cfg, NOTES, "t", "s1", date=dt.date(2026, 7, 16))
    p2 = vault.save_note(cfg, NOTES, "t", "s2", date=dt.date(2026, 7, 16))
    assert p1 != p2 and p2.name.endswith("-2.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_vault.py -v`
Expected: FAIL (ModuleNotFoundError: miris.vault).

- [ ] **Step 3: Implement `miris/vault.py`**

```python
"""Render the meeting note and write it into the vault."""
import datetime as dt
import re
import unicodedata
from pathlib import Path

from miris.config import Config


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len] or "reuniao"


def render_note(notes: dict, transcript: str, session_id: str, date: dt.date) -> str:
    items = "\n".join(f"- [ ] {i}" for i in notes.get("action_items", []))
    return f"""---
title: {notes['titulo']}
date: {date.isoformat()}
categoria: {notes['categoria']}
source: miris
session: {session_id}
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
    path.write_text(render_note(notes, transcript, session_id, date))
    return path
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_vault.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add miris/vault.py tests/test_vault.py
git commit -m "feat: vault note rendering, category routing, inbox fallback"
```

---

### Task 3: LLM notes generation

**Files:**
- Create: `miris/notes.py`
- Test: `tests/test_notes.py`

**Interfaces:**
- Consumes: `miris.config.Config` (`llm_command`, `categories`).
- Produces: `NotesError(Exception)`; `build_prompt(categories: list[str], transcript: str) -> str`; `generate(cfg: Config, transcript: str, timeout_s: int = 300) -> dict` returning keys `categoria`, `titulo`, `resumo`, `action_items`. Raises `NotesError` on command failure, bad JSON, or missing keys. The prompt instructs the model to answer `"outros"` when no category fits (unknown categories route to inbox in vault.py).

- [ ] **Step 1: Write the failing test**

`tests/test_notes.py`:
```python
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


def test_generate_raises_on_nonzero_exit(tmp_path):
    cfg = _cfg(tmp_path, "exit 3")
    with pytest.raises(notes.NotesError):
        notes.generate(cfg, "t")


def test_generate_raises_on_missing_key(tmp_path):
    cfg = _cfg(tmp_path, "echo '{\"titulo\": \"x\"}'")
    with pytest.raises(notes.NotesError):
        notes.generate(cfg, "t")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_notes.py -v`
Expected: FAIL (ModuleNotFoundError: miris.notes).

- [ ] **Step 3: Implement `miris/notes.py`**

```python
"""Summary + classification via the configured LLM CLI (agy by default)."""
import json
import re
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


def _extract_json(text: str) -> str:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise NotesError(f"no JSON object in LLM output: {text[:200]!r}")
    return match.group(0)


def generate(cfg: Config, transcript: str, timeout_s: int = 300) -> dict:
    prompt = build_prompt(list(cfg.categories), transcript)
    try:
        proc = subprocess.run(cfg.llm_command + [prompt], capture_output=True,
                              text=True, timeout=timeout_s)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NotesError(f"llm command failed: {exc}") from exc
    if proc.returncode != 0:
        raise NotesError(f"llm exit {proc.returncode}: {proc.stderr[:200]}")
    try:
        result = json.loads(_extract_json(proc.stdout))
    except json.JSONDecodeError as exc:
        raise NotesError(f"bad JSON from llm: {exc}") from exc
    for key in ("categoria", "titulo", "resumo", "action_items"):
        if key not in result:
            raise NotesError(f"missing key {key!r} in llm output")
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_notes.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add miris/notes.py tests/test_notes.py
git commit -m "feat: LLM notes generation via configurable CLI command"
```

---

### Task 4: Transcription and timeline merge

**Files:**
- Create: `miris/transcribe.py`
- Test: `tests/test_transcribe.py`

**Interfaces:**
- Consumes: `laris.transcriber.Transcriber` (duck-typed: `.transcribe(audio: np.ndarray) -> str`), silero-vad (already a laris dependency).
- Produces: `Segment` frozen dataclass `(start_s: float, end_s: float, speaker: str, text: str)`; `TARGET_SR = 16000`; `load_wav_mono16k(path: Path) -> np.ndarray`; `speech_spans(audio: np.ndarray, sr: int = TARGET_SR) -> list[tuple[int, int]]` (sample offsets); `transcribe_channel(path: Path, speaker: str, transcriber, spans_fn=speech_spans) -> list[Segment]`; `merge(*channels: list[Segment]) -> str` producing `[mm:ss] Speaker: text` lines sorted by start time.

- [ ] **Step 1: Write the failing test**

`tests/test_transcribe.py`:
```python
import wave
from pathlib import Path

import numpy as np

from miris import transcribe
from miris.transcribe import Segment


def _write_wav(path: Path, audio: np.ndarray, sr: int, channels: int = 1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def test_load_wav_16k_mono_roundtrip(tmp_path):
    audio = np.sin(np.linspace(0, 100, 16000)).astype(np.float32) * 0.5
    _write_wav(tmp_path / "a.wav", audio, 16000)
    loaded = transcribe.load_wav_mono16k(tmp_path / "a.wav")
    assert loaded.shape == (16000,)
    assert np.abs(loaded - audio).max() < 0.01


def test_load_wav_downmixes_and_resamples(tmp_path):
    stereo = np.zeros(48000 * 2, dtype=np.float32)  # 1s of 48k stereo interleaved
    _write_wav(tmp_path / "b.wav", stereo, 48000, channels=2)
    loaded = transcribe.load_wav_mono16k(tmp_path / "b.wav")
    assert abs(len(loaded) - 16000) <= 1


def test_transcribe_channel_uses_spans_and_transcriber(tmp_path):
    audio = np.zeros(32000, dtype=np.float32)  # 2s @16k
    _write_wav(tmp_path / "c.wav", audio, 16000)

    class FakeTranscriber:
        def transcribe(self, chunk):
            return f"len={len(chunk)}"

    spans = lambda a, sr=16000: [(0, 16000), (16000, 32000)]
    segs = transcribe.transcribe_channel(tmp_path / "c.wav", "Eu", FakeTranscriber(), spans_fn=spans)
    assert segs == [
        Segment(0.0, 1.0, "Eu", "len=16000"),
        Segment(1.0, 2.0, "Eu", "len=16000"),
    ]


def test_merge_interleaves_by_timestamp():
    me = [Segment(0.0, 1.0, "Eu", "oi"), Segment(65.0, 66.0, "Eu", "tchau")]
    them = [Segment(2.5, 4.0, "Eles", "olá")]
    assert transcribe.merge(me, them) == (
        "[00:00] Eu: oi\n[00:02] Eles: olá\n[01:05] Eu: tchau"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_transcribe.py -v`
Expected: FAIL (ModuleNotFoundError: miris.transcribe).

- [ ] **Step 3: Implement `miris/transcribe.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_transcribe.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add miris/transcribe.py tests/test_transcribe.py
git commit -m "feat: VAD-chunked per-channel transcription and timeline merge"
```

---

### Task 5: Swift audiotap helper + Python wrapper

**Files:**
- Create: `helper/audiotap.swift`, `helper/Makefile`, `miris/systemtap.py`
- Test: `tests/test_systemtap.py`

**Interfaces:**
- Produces: `miris.systemtap.SystemTap(out_wav: Path, binary: Path | None = None)` with `.start()` (raises `FileNotFoundError` if binary missing), `.alive() -> bool`, `.stop(grace_s: float = 5.0)` (SIGTERM then SIGKILL). Env var `MIRIS_AUDIOTAP` overrides the binary path. Helper contract: `audiotap <out.wav>` records global system audio until SIGTERM/SIGINT, finalizes the WAV, exits 0.

- [ ] **Step 1: Write the failing test (wrapper only — fake helper script)**

`tests/test_systemtap.py`:
```python
import time
from pathlib import Path

import pytest

from miris.systemtap import SystemTap

FAKE_HELPER = """#!/bin/sh
trap 'echo done >> "$1"; exit 0' TERM INT
echo started > "$1"
while true; do sleep 0.1; done
"""


def _fake_binary(tmp_path) -> Path:
    binary = tmp_path / "fake_audiotap"
    binary.write_text(FAKE_HELPER)
    binary.chmod(0o755)
    return binary


def test_start_raises_when_binary_missing(tmp_path):
    tap = SystemTap(tmp_path / "out.wav", binary=tmp_path / "nope")
    with pytest.raises(FileNotFoundError):
        tap.start()


def test_lifecycle_start_alive_stop(tmp_path):
    out = tmp_path / "out.wav"
    tap = SystemTap(out, binary=_fake_binary(tmp_path))
    tap.start()
    time.sleep(0.3)
    assert tap.alive()
    tap.stop()
    assert not tap.alive()
    assert "done" in out.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_systemtap.py -v`
Expected: FAIL (ModuleNotFoundError: miris.systemtap).

- [ ] **Step 3: Implement `miris/systemtap.py`**

```python
"""Own the audiotap helper process (system-audio capture)."""
import os
import signal
import subprocess
from pathlib import Path

DEFAULT_BIN = Path(__file__).resolve().parent.parent / "helper" / "audiotap"


class SystemTap:
    def __init__(self, out_wav: Path, binary: Path | None = None):
        self.out_wav = out_wav
        env_bin = os.environ.get("MIRIS_AUDIOTAP")
        self.binary = Path(env_bin) if env_bin else Path(binary or DEFAULT_BIN)
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        if not self.binary.exists():
            raise FileNotFoundError(
                f"audiotap binary not found: {self.binary} (run: make -C helper)")
        self.proc = subprocess.Popen([str(self.binary), str(self.out_wav)])

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, grace_s: float = 5.0) -> None:
        if self.proc is None or self.proc.poll() is not None:
            return
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_systemtap.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Write the Swift helper**

`helper/audiotap.swift` — global Core Audio process tap → 16-bit WAV. NOTE for the implementer: this is macOS 14.2+ API; if `swiftc` reports a renamed constant or initializer, fix against the local SDK headers (`AudioHardwareTapping.h`, `CATapDescription.h`) — the structure (tap → aggregate with tap list → IOProc → ExtAudioFile) is the contract, exact spellings may drift.

```swift
// audiotap.swift - global system-audio tap -> WAV. macOS 14.2+.
// Usage: audiotap <out.wav>  (records until SIGTERM/SIGINT)
import Foundation
import CoreAudio
import AudioToolbox

func check(_ status: OSStatus, _ what: String) {
    guard status == noErr else {
        FileHandle.standardError.write("audiotap: \(what) failed: \(status)\n".data(using: .utf8)!)
        exit(1)
    }
}

guard CommandLine.arguments.count == 2 else {
    FileHandle.standardError.write("usage: audiotap <out.wav>\n".data(using: .utf8)!)
    exit(2)
}
let outURL = URL(fileURLWithPath: CommandLine.arguments[1])

// 1. Global tap: everything the system plays, no excluded processes.
let tapDesc = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
tapDesc.name = "miris-audiotap"
tapDesc.isPrivate = true
tapDesc.muteBehavior = .unmuted
var tapID = AudioObjectID(kAudioObjectUnknown)
check(AudioHardwareCreateProcessTap(tapDesc, &tapID), "create tap")

// 2. Tap stream format.
var fmtAddr = AudioObjectPropertyAddress(
    mSelector: kAudioTapPropertyFormat,
    mScope: kAudioObjectPropertyScopeGlobal,
    mElement: kAudioObjectPropertyElementMain)
var asbd = AudioStreamBasicDescription()
var size = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
check(AudioObjectGetPropertyData(tapID, &fmtAddr, 0, nil, &size, &asbd), "get tap format")

// 3. Private aggregate device containing only the tap.
let aggDict: [String: Any] = [
    kAudioAggregateDeviceNameKey: "miris-agg",
    kAudioAggregateDeviceUIDKey: UUID().uuidString,
    kAudioAggregateDeviceIsPrivateKey: true,
    kAudioAggregateDeviceTapListKey: [
        [kAudioSubTapUIDKey: tapDesc.uuid.uuidString]
    ],
]
var aggID = AudioObjectID(kAudioObjectUnknown)
check(AudioHardwareCreateAggregateDevice(aggDict as CFDictionary, &aggID), "create aggregate")

// 4. WAV writer: ExtAudioFile converts tap float32 -> 16-bit PCM on disk.
var outFmt = AudioStreamBasicDescription(
    mSampleRate: asbd.mSampleRate,
    mFormatID: kAudioFormatLinearPCM,
    mFormatFlags: kLinearPCMFormatFlagIsSignedInteger | kLinearPCMFormatFlagIsPacked,
    mBytesPerPacket: 2 * asbd.mChannelsPerFrame,
    mFramesPerPacket: 1,
    mBytesPerFrame: 2 * asbd.mChannelsPerFrame,
    mChannelsPerFrame: asbd.mChannelsPerFrame,
    mBitsPerChannel: 16,
    mReserved: 0)
var extFile: ExtAudioFileRef?
check(ExtAudioFileCreateWithURL(outURL as CFURL, kAudioFileWAVEType, &outFmt, nil,
                                AudioFileFlags.eraseFile.rawValue, &extFile), "create wav")
check(ExtAudioFileSetProperty(extFile!, kExtAudioFileProperty_ClientDataFormat,
                              UInt32(MemoryLayout<AudioStreamBasicDescription>.size), &asbd),
      "set client format")

// 5. IO proc: each callback delivers tap buffers; write them straight out.
var procID: AudioDeviceIOProcID?
check(AudioDeviceCreateIOProcIDWithBlock(&procID, aggID, nil) { _, inData, _, _, _ in
    let frames = inData.pointee.mBuffers.mDataByteSize / asbd.mBytesPerFrame
    _ = ExtAudioFileWrite(extFile!, frames, inData)
}, "create io proc")
check(AudioDeviceStart(aggID, procID!), "start device")

// 6. Record until SIGTERM/SIGINT, then tear down in order.
let stop = DispatchSemaphore(value: 0)
let termSrc = DispatchSource.makeSignalSource(signal: SIGTERM)
let intSrc = DispatchSource.makeSignalSource(signal: SIGINT)
for src in [termSrc, intSrc] {
    src.setEventHandler { stop.signal() }
    src.resume()
}
signal(SIGTERM, SIG_IGN)
signal(SIGINT, SIG_IGN)
stop.wait()

AudioDeviceStop(aggID, procID!)
AudioDeviceDestroyIOProcID(aggID, procID!)
AudioHardwareDestroyAggregateDevice(aggID)
AudioHardwareDestroyProcessTap(tapID)
ExtAudioFileDispose(extFile!)
exit(0)
```

`helper/Makefile`:
```make
audiotap: audiotap.swift
	swiftc -O -framework CoreAudio -framework AudioToolbox -o audiotap audiotap.swift

clean:
	rm -f audiotap
```

- [ ] **Step 6: Build and smoke-test the helper**

Run: `make -C helper && ./helper/audiotap /tmp/tap-test.wav & sleep 3; kill -TERM %1; wait; ls -la /tmp/tap-test.wav`

Expected: binary compiles; first run triggers the macOS "System Audio Recording" permission prompt (approve it — it lands under Privacy & Security → Screen & System Audio Recording); WAV exists and is > 44 bytes. Play some audio during the 3s and verify content with `afplay /tmp/tap-test.wav`. If compile fails on a constant name, fix per the note in Step 5.

- [ ] **Step 7: Commit**

```bash
git add helper/ miris/systemtap.py tests/test_systemtap.py
git commit -m "feat: Core Audio system-tap helper and process wrapper"
```

---

### Task 6: Recorder process

**Files:**
- Create: `miris/recorder.py`
- Test: `tests/test_recorder.py`

**Interfaces:**
- Consumes: `miris.systemtap.SystemTap`.
- Produces: `WavWriter(path: Path, sample_rate: int = 16000)` with `.write(chunk: np.ndarray)` (float32 [-1,1] mono) and `.close()`; `record(session_dir: Path, stop: threading.Event, tap_factory=SystemTap, open_stream=None)` writing `mic.wav` + `system.wav`; module runnable as `python -m miris.recorder <session_dir>` — writes `recorder.pid` once recording, removes it on clean exit, stops on SIGTERM/SIGINT. Task 7 relies on the pidfile protocol and on `sys.executable -m miris.recorder <dir>` as spawn command.

- [ ] **Step 1: Write the failing test**

`tests/test_recorder.py`:
```python
import threading
import time
import wave
from pathlib import Path

import numpy as np

from miris import recorder


def test_wavwriter_roundtrip(tmp_path):
    path = tmp_path / "m.wav"
    w = recorder.WavWriter(path, sample_rate=16000)
    w.write(np.ones(1600, dtype=np.float32) * 0.5)
    w.close()
    with wave.open(str(path), "rb") as f:
        assert f.getnchannels() == 1
        assert f.getframerate() == 16000
        assert f.getnframes() == 1600


class FakeTap:
    def __init__(self, out_wav, binary=None):
        self.out_wav = Path(out_wav)
        self.stopped = False

    def start(self):
        self.out_wav.write_bytes(b"RIFF")

    def alive(self):
        return not self.stopped

    def stop(self, grace_s=5.0):
        self.stopped = True


def test_record_writes_both_channels_and_stops(tmp_path):
    stop = threading.Event()
    chunks = [np.zeros(1600, dtype=np.float32)] * 3

    class FakeStream:
        def __init__(self, cb):
            self._cb = cb

        def __enter__(self):
            for c in chunks:
                self._cb(c.reshape(-1, 1), len(c), None, None)
            return self

        def __exit__(self, *a):
            return False

    taps = []

    def tap_factory(out_wav, binary=None):
        tap = FakeTap(out_wav)
        taps.append(tap)
        return tap

    timer = threading.Timer(0.3, stop.set)
    timer.start()
    recorder.record(tmp_path, stop, tap_factory=tap_factory,
                    open_stream=lambda cb: FakeStream(cb))
    timer.cancel()

    assert taps[0].stopped
    assert (tmp_path / "system.wav").exists()
    with wave.open(str(tmp_path / "mic.wav"), "rb") as f:
        assert f.getnframes() == 3 * 1600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_recorder.py -v`
Expected: FAIL (ModuleNotFoundError: miris.recorder).

- [ ] **Step 3: Implement `miris/recorder.py`**

```python
"""Recording process: mic -> mic.wav, audiotap helper -> system.wav.
Runs until SIGTERM/SIGINT; finalizes both WAVs on the way out.
Spawned detached by `miris start` as: python -m miris.recorder <session_dir>."""
import os
import queue
import signal
import sys
import threading
import wave
from pathlib import Path

import numpy as np

from miris.systemtap import SystemTap

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1600  # 100ms


class WavWriter:
    """Incremental 16-bit PCM mono WAV writer."""

    def __init__(self, path: Path, sample_rate: int = SAMPLE_RATE):
        self._wav = wave.open(str(path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(sample_rate)

    def write(self, chunk: np.ndarray) -> None:
        pcm = np.clip(chunk, -1.0, 1.0)
        self._wav.writeframes((pcm * 32767).astype(np.int16).tobytes())

    def close(self) -> None:
        self._wav.close()


def _default_open_stream(callback):
    import sounddevice as sd
    return sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                          blocksize=CHUNK_SAMPLES, callback=callback)


def record(session_dir: Path, stop: threading.Event,
           tap_factory=SystemTap, open_stream=None) -> None:
    tap = tap_factory(session_dir / "system.wav")
    tap.start()
    writer = WavWriter(session_dir / "mic.wav")
    open_stream = open_stream or _default_open_stream
    q: queue.Queue[np.ndarray] = queue.Queue()

    def _cb(indata, frames, time_info, status):
        q.put(indata[:, 0].copy())

    try:
        with open_stream(_cb):
            while not stop.is_set():
                try:
                    writer.write(q.get(timeout=0.2))
                except queue.Empty:
                    pass
            while not q.empty():
                writer.write(q.get_nowait())
    finally:
        writer.close()
        tap.stop()


def main() -> None:
    session_dir = Path(sys.argv[1])
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    pid_file = session_dir / "recorder.pid"
    pid_file.write_text(str(os.getpid()))
    try:
        record(session_dir, stop)
    finally:
        pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_recorder.py -v`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add miris/recorder.py tests/test_recorder.py
git commit -m "feat: detached recorder process for mic and system channels"
```

---

### Task 7: Pipeline + CLI

**Files:**
- Create: `miris/pipeline.py`, `miris/cli.py`
- Test: `tests/test_pipeline.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above. `pipeline.process_session(cfg, session_dir, transcriber_factory=None) -> Path` (path of the saved note); caches `transcript.md` in the session dir; on `NotesError` builds fallback notes dict (`categoria="__falha__"` → routes to inbox) and still saves. `cli.main()` — argparse entry point with subcommands `start`, `stop`, `status`, `retry <session-id>`, `doctor`.
- Produces: the `miris` console script (wired in Task 1's pyproject).

- [ ] **Step 1: Write the failing pipeline test**

`tests/test_pipeline.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_pipeline.py -v`
Expected: FAIL (ModuleNotFoundError: miris.pipeline).

- [ ] **Step 3: Implement `miris/pipeline.py`**

```python
"""Post-meeting pipeline: WAVs -> transcript -> notes -> vault note."""
import json
from pathlib import Path

from miris import notes as notes_mod
from miris import transcribe, vault
from miris.config import Config

CHANNELS = (("mic.wav", "Eu"), ("system.wav", "Eles"))
WAV_HEADER_BYTES = 44


def _default_transcriber_factory():
    from laris.transcriber import Transcriber
    return Transcriber()


def build_transcript(session_dir: Path, transcriber_factory=None) -> str:
    factory = transcriber_factory or _default_transcriber_factory
    transcriber = factory()
    if hasattr(transcriber, "warm"):
        transcriber.warm()
    channels = []
    for wav_name, speaker in CHANNELS:
        path = session_dir / wav_name
        if path.exists() and path.stat().st_size > WAV_HEADER_BYTES:
            try:
                channels.append(transcribe.transcribe_channel(path, speaker, transcriber))
            except Exception as exc:  # helper killed mid-meeting leaves a broken WAV
                print(f"[transcribe] {wav_name} unreadable ({exc}) - continuing without it")
    return transcribe.merge(*channels)


def process_session(cfg: Config, session_dir: Path, transcriber_factory=None) -> Path:
    transcript_path = session_dir / "transcript.md"
    if transcript_path.exists():
        transcript = transcript_path.read_text()
    else:
        transcript = build_transcript(session_dir, transcriber_factory)
        transcript_path.write_text(transcript)

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
        json.dumps(notes, ensure_ascii=False, indent=2))
    return vault.save_note(cfg, notes, transcript, session_dir.name)
```

- [ ] **Step 4: Run pipeline tests to verify they pass**

Run: `.venv/bin/pytest tests/test_pipeline.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Write the failing CLI test**

`tests/test_cli.py`:
```python
import os

from miris.config import Config
from miris import cli


def _cfg(tmp_path) -> Config:
    return Config(vault_root=tmp_path / "vault", inbox="inbox", llm_command=["true"],
                  categories={}, sessions_dir=tmp_path / "sessions")


def test_live_session_none_when_empty(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.sessions_dir.mkdir(parents=True)
    assert cli._live_session(cfg) == (None, None)


def test_live_session_finds_running_pid(tmp_path):
    cfg = _cfg(tmp_path)
    session = cfg.sessions_dir / "20260716-1000"
    session.mkdir(parents=True)
    (session / "recorder.pid").write_text(str(os.getpid()))
    assert cli._live_session(cfg) == (session, os.getpid())


def test_live_session_cleans_stale_pid(tmp_path):
    cfg = _cfg(tmp_path)
    session = cfg.sessions_dir / "20260716-1000"
    session.mkdir(parents=True)
    (session / "recorder.pid").write_text("999999999")
    assert cli._live_session(cfg) == (None, None)
    assert not (session / "recorder.pid").exists()
```

- [ ] **Step 6: Run CLI test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: FAIL (ModuleNotFoundError: miris.cli).

- [ ] **Step 7: Implement `miris/cli.py`**

```python
"""miris - meeting recorder CLI: start | stop | status | retry | doctor."""
import argparse
import datetime as dt
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from miris import config, pipeline


def _live_session(cfg: config.Config):
    """Newest session with a live recorder pid, or (None, None). Stale pidfiles
    (process gone) are removed on the way."""
    if not cfg.sessions_dir.exists():
        return None, None
    for session in sorted(cfg.sessions_dir.iterdir(), reverse=True):
        pid_file = session / "recorder.pid"
        if not pid_file.exists():
            continue
        pid = int(pid_file.read_text())
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            pid_file.unlink(missing_ok=True)
            continue
        return session, pid
    return None, None


def cmd_start(cfg: config.Config) -> None:
    session, pid = _live_session(cfg)
    if session:
        sys.exit(f"already recording: {session.name} (pid {pid})")
    session = cfg.sessions_dir / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    session.mkdir(parents=True)
    subprocess.Popen([sys.executable, "-m", "miris.recorder", str(session)],
                     start_new_session=True)
    for _ in range(50):
        if (session / "recorder.pid").exists():
            print(f"recording -> {session}")
            return
        time.sleep(0.1)
    sys.exit("recorder did not start (check mic / system-audio permissions)")


def cmd_stop(cfg: config.Config) -> None:
    session, pid = _live_session(cfg)
    if not session:
        sys.exit("no active recording")
    os.kill(pid, signal.SIGTERM)
    while (session / "recorder.pid").exists():
        time.sleep(0.2)
    print("recording finished, processing...")
    note = pipeline.process_session(cfg, session)
    print(f"note: {note}")


def cmd_status(cfg: config.Config) -> None:
    session, pid = _live_session(cfg)
    if session:
        mic = session / "mic.wav"
        size = mic.stat().st_size if mic.exists() else 0
        print(f"recording: {session.name} (pid {pid}, mic.wav {size} bytes)")
    else:
        print("idle")


def cmd_retry(cfg: config.Config, session_id: str) -> None:
    session = cfg.sessions_dir / session_id
    if not session.is_dir():
        sys.exit(f"unknown session: {session_id}")
    note = pipeline.process_session(cfg, session)
    print(f"note: {note}")


def cmd_doctor(cfg: config.Config) -> None:
    from miris.systemtap import SystemTap
    ok = True

    tap_bin = SystemTap(Path("/dev/null")).binary
    print(f"[{'ok' if tap_bin.exists() else 'FAIL'}] audiotap binary: {tap_bin}")
    ok &= tap_bin.exists()

    print(f"[{'ok' if cfg.vault_root.is_dir() else 'FAIL'}] vault_root: {cfg.vault_root}")
    ok &= cfg.vault_root.is_dir()

    print(f"[{'ok' if cfg.categories else 'WARN'}] categories configured: "
          f"{list(cfg.categories) or 'none (everything goes to inbox)'}")

    llm = subprocess.run(cfg.llm_command + ["Responda apenas: OK"],
                         capture_output=True, text=True, timeout=120)
    llm_ok = llm.returncode == 0 and llm.stdout.strip() != ""
    print(f"[{'ok' if llm_ok else 'FAIL'}] llm_command: {' '.join(cfg.llm_command)}")
    ok &= llm_ok

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "tap-smoke.wav"
        tap = SystemTap(out)
        if tap_bin.exists():
            tap.start()
            time.sleep(3)
            tap.stop()
            tap_worked = out.exists() and out.stat().st_size > 44
            print(f"[{'ok' if tap_worked else 'FAIL'}] system-audio smoke "
                  f"(3s): {out.stat().st_size if out.exists() else 0} bytes")
            ok &= tap_worked

    sys.exit(0 if ok else 1)


def main() -> None:
    parser = argparse.ArgumentParser(prog="miris")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("status")
    retry = sub.add_parser("retry")
    retry.add_argument("session_id")
    sub.add_parser("doctor")
    args = parser.parse_args()

    cfg = config.load()
    if args.command == "start":
        cmd_start(cfg)
    elif args.command == "stop":
        cmd_stop(cfg)
    elif args.command == "status":
        cmd_status(cfg)
    elif args.command == "retry":
        cmd_retry(cfg, args.session_id)
    elif args.command == "doctor":
        cmd_doctor(cfg)


if __name__ == "__main__":
    main()
```

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all tests PASS (config 2, vault 4, notes 5, transcribe 4, systemtap 2, recorder 2, pipeline 3, cli 3).

- [ ] **Step 9: Commit**

```bash
git add miris/pipeline.py miris/cli.py tests/test_pipeline.py tests/test_cli.py
git commit -m "feat: post-meeting pipeline and miris CLI"
```

---

### Task 8: End-to-end validation + README

**Files:**
- Create: `README.md`
- Modify: nothing else expected; fix whatever the live run surfaces.

**Interfaces:**
- Consumes: everything. This task is the live verification gate — no new code unless the smoke run fails.

- [ ] **Step 1: Live smoke run (real hardware, real agy)**

```bash
cd ~/code/miris && source .venv/bin/activate
miris doctor          # expect: all [ok]; first run triggers the System Audio Recording permission prompt
miris start           # play a YouTube video AND speak into the mic
sleep 30 && miris stop
```

Expected: `miris stop` prints a vault note path; the note has frontmatter, Resumo, Action items, and a Transcript with both `Eu:` (your mic speech) and `Eles:` (the video audio) lines with plausible timestamps.

- [ ] **Step 2: Verify failure path**

```bash
# break the llm on purpose, confirm inbox fallback + retry
MIRIS_HOME=$(mktemp -d) miris start   # NOTE: fresh home also needs config edit; simpler:
# edit ~/.miris/config.toml -> llm_command = ["false"]; then:
miris start && sleep 10 && miris stop   # expect: note in ~/vault/inbox, retry hint printed
# restore llm_command = ["agy", "--model", "Gemini 3.5 Flash (Medium)", "-p"]
miris retry <session-id>                # expect: proper categorized note
```

- [ ] **Step 3: Write `README.md`**

```markdown
# MIRIS

Meeting Intelligence Recording & Insight System - local Krisp-style meeting
recorder for macOS (sibling of [LARIS](https://github.com/sammyjdev/laris)).
Records both sides of any call (mic + system audio via a Core Audio process
tap - Discord, Zoom, Teams, Meet, anything the Mac plays), transcribes
locally with mlx-whisper (pt-BR), then asks the configured LLM CLI (`agy`
by default) for a summary, action items and a category, and saves the note
into the Obsidian vault folder mapped to that category.

## Requirements

- macOS 14.2+ (Core Audio process tap), Apple Silicon (mlx-whisper)
- Xcode CLT (`swiftc`) to build the audio helper
- [Antigravity CLI](https://antigravity.google) logged in (`agy`), or edit
  `llm_command` in the config to any prompt-in/text-out CLI

## Setup

```bash
git clone git@github.com:sammyjdev/laris.git ~/code/laris   # sibling dep
cd ~/code/miris
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make -C helper          # builds helper/audiotap
miris doctor            # triggers the System Audio Recording permission prompt
```

## Use

```bash
miris start     # begin recording (detached; survives closing the terminal)
miris status
miris stop      # stop, transcribe, summarize, save note to the vault
miris retry <session-id>   # re-run summary/classification for a session
```

Config: `~/.miris/config.toml` (created on first run) - vault root, category
-> folder map, `llm_command`. Raw WAVs stay in `~/.miris/sessions/<ts>/`
until you delete them.

## Testing

```bash
pytest -q
```
```

- [ ] **Step 4: Final commit**

```bash
git add README.md
git commit -m "docs: README with setup, usage and permissions notes"
```
