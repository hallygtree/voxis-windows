# MIRIS Core — Design

**Date:** 2026-07-16
**Status:** Draft — awaiting user review
**Phase:** 1 of 4 (core engine; menu bar UI, orb themes and KIRIS retirement are separate phases/specs)

## What

MIRIS (Meeting Intelligence Recording & Insight System) is a local, Krisp-style
meeting recorder for macOS. It records both sides of any call (Discord, Zoom,
Teams, Meet — app-agnostic), transcribes locally with mlx-whisper, then uses
the Antigravity CLI (`agy -p`, Gemini subscription) to generate a summary with
action items and classify the meeting into a user-defined category. The final
note lands in the Obsidian vault (`~/vault`) folder mapped to that category.

Sibling package to LARIS/KIRIS: lives at `~/code/miris`, depends on `laris`
as an editable lib (reuses `Transcriber` and the DeepFilterNet denoise —
zero code copied).

## Explicit decisions

| Decision | Choice | Why |
|----------|--------|-----|
| System audio capture | Core Audio process tap via a small Swift helper (macOS 14.2+ API) | Native, no BlackHole driver, no audio-setup pollution, captures everything the Mac plays regardless of app |
| Channels | Mic and system recorded as two separate WAV files | Free "Me vs Them" diarization by construction — no speaker model |
| Transcription timing | Post-meeting (on `miris stop`) | Simpler; live transcript was not requested |
| STT | `laris.Transcriber` (mlx-whisper, pt-BR, Metal) | Already tuned and production-proven in LARIS |
| Summary/classification LLM | `agy -p` (Antigravity CLI, Gemini) | User has Gemini subscription; validated 2026-07-16: clean JSON out, correct category, ~8s. Note: gemini-cli itself stopped serving AI Pro/Ultra logins on 2026-06-18 — agy is the supported path |
| Model | `Gemini 3.5 Flash (Medium)` (agy `--model` takes the display name verbatim) | Summarization is easy; Flash spends least quota. Upgrade path: `Gemini 3.1 Pro (Low)` via config if summaries feel shallow. Command+model live in `llm_command` config, not code — offloads the idle Google subscription and keeps Anthropic/OpenAI quota for coding |
| Classification | Fixed category list from config; LLM picks from the list only | Open-ended classification misfiles notes |
| Fallback | Unparseable/unknown category → `~/vault/inbox/` | Never guess a destination; never lose a note |
| Start/stop | Manual CLI (`miris start` / `miris stop`) | Auto-detect is a later layer; auto-recording without confirmation is a privacy footgun |
| Raw audio retention | WAVs kept in `~/.miris/sessions/<ts>/` until user deletes | Reprocessing raw material is cheap insurance |

## Architecture

```
~/code/miris/
  pyproject.toml            # sibling-standard packaging (like laris/kiris)
  miris/
    cli.py                  # miris start | stop | status | doctor
    config.py               # categories → vault folders; model; paths
    recorder.py             # session lifecycle: mic (sounddevice) + system (helper) → 2 WAVs
    systemtap.py            # Python wrapper: spawn/stop the Swift helper binary
    transcribe.py           # chunked mlx-whisper per channel → merged timeline
    notes.py                # agy -p: summary + action items + category (fixed list)
    vault.py                # render markdown note, write to ~/vault/<category folder>/
  helper/
    audiotap.swift          # ~100-line Core Audio tap → WAV on disk (or stdout)
    Makefile                # swiftc build; binary checked into .gitignore, built by make
  tests/                    # pytest: pure modules only (no audio hardware)
```

### Data flow

```
miris start
  ├─ recorder: sounddevice mic stream  → ~/.miris/sessions/<ts>/mic.wav
  └─ systemtap: swift helper (CATap)   → ~/.miris/sessions/<ts>/system.wav
miris stop
  ├─ transcribe: VAD-chunk each WAV → mlx-whisper per chunk, keep offsets
  ├─ merge: interleave chunks by timestamp → "[mm:ss] Eu:" / "[mm:ss] Eles:"
  ├─ notes: agy -p '<prompt + transcript>' → JSON {categoria, titulo, resumo, action_items}
  └─ vault: ~/vault/<folder(categoria)>/YYYY-MM-DD-<slug>.md
            (note = frontmatter + resumo + action items + full transcript appended)
```

### Component contracts

- **systemtap.py → helper**: spawns `helper/audiotap <out.wav>`; helper records
  a global system-audio tap until SIGTERM, then finalizes the WAV header and
  exits 0. Wrapper owns process lifecycle and reports health (file growing?).
- **transcribe.py**: `(wav_path, speaker_label) -> list[Segment]` where
  `Segment = (start_s, end_s, speaker, text)`. Chunking reuses Silero VAD from
  laris so hour-long audio never hits whisper as one blob.
  `merge(segments_a, segments_b) -> str` is a pure function (easy to test).
- **notes.py**: builds the prompt (categories injected from config), calls
  `agy -p`, parses strict JSON. Parse failure or category not in list →
  returns fallback marker; vault.py then writes to inbox. `agy` requires
  network + Keychain: it must run unsandboxed (normal daemon context).
- **config.py**: TOML at `~/.miris/config.toml`:
  ```toml
  vault_root = "~/vault"
  inbox = "inbox"
  # provider-agnostic on purpose: Google killed gemini-cli logins mid-2026;
  # swapping to "claude -p" / "codex exec" must be a config edit, not code.
  llm_command = ["agy", "--model", "Gemini 3.5 Flash (Medium)", "-p"]
  [categories]
  trabalho-empresa-x = "work/empresa-x/meetings"
  minhas-empresas    = "own/meetings"
  entrevistas        = "interviews"
  estudo             = "study/meetings"
  ```

### Error handling

- Helper dies mid-meeting → recorder notices (process exit), keeps recording
  mic, flags the session; transcript proceeds with mic-only and the note says
  system audio was lost.
- `agy` fails (offline, auth expired) → transcript-only note goes to inbox;
  `miris retry <session>` re-runs the notes step later.
- `miris stop` crash mid-transcription → WAVs are intact on disk; `miris retry`
  covers reprocessing.

### Testing / validation

- pytest (no audio hardware): merge timeline, JSON parsing incl. malformed
  output, category routing incl. fallback, note rendering, config parsing.
- `miris doctor`: end-to-end smoke — records 3s of mic+system, asserts both
  WAVs are non-empty, runs a 1-token `agy -p` ping, checks vault path exists.
- Swift helper: manual smoke via doctor (documented in README); no unit tests
  for the helper itself.

## Out of scope (later phases)

- Menu bar app (phase 2): start/stop UI, recording indicator icon, LARIS
  toggles, orb theme selector.
- Orb visual redesign + themes (phase 3).
- KIRIS retirement housekeeping (phase 4).
- Live transcription, meeting auto-detect, speaker diarization beyond
  Me/Them, claude-code-ops panel rethink.
