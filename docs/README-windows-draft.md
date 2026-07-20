# VOXIS — README (rascunho pós-paridade Windows)

> Rascunho preparado antes do trabalho começar. **Não substitui o
> `README.md` atual.** Quando o ditado e as reuniões estiverem funcionando de
> ponta a ponta no Windows (ver critérios de aceite em
> `docs/superpowers/plans/`), revisar este texto e promovê-lo a `README.md`
> antes de tornar o repositório público e abrir o PR para
> [`sammyjdev/voxis`](https://github.com/sammyjdev/voxis).

---

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="brand/voxis-wordmark-dark.svg">
    <img src="brand/voxis-wordmark-light.svg" alt="VOXIS" width="360">
  </picture>
</p>

<p align="center">
  Local-first voice product family. The "O" is the orb - a circular waveform
  that lights up when VOXIS listens.
</p>

---

## Family

| Package | What |
|---------|------|
| `packages/laris` | Dictation engine — push-to-talk / hands-free local STT, desktop orb overlay, themeable (`/theme` API). Funciona em macOS e Windows. |
| `packages/miris` | Meeting engine — records mic + system audio, transcribes locally, LLM summary + classification into the Obsidian vault. Funciona em macOS e Windows. |
| `apps/tray` | Tray app (Tauri v2) — record meetings, dictation toggles, orb theme, native settings window. |
| `brand/` | Wordmark, mark and menu-bar variants (SVG) |

Each package keeps its own venv, tests and README — see inside.

## Install

Full steps per component and per OS: **[docs/INSTALL.md](docs/INSTALL.md)**.

O instalador do tray (`.msi`/`.exe`) já inclui os dois motores prontos —
não é preciso Python nem Rust para usar o app no Windows. Baixe pela
[Releases page](https://github.com/sammyjdev/voxis/releases) (sem
assinatura ainda — veja o passo único de SmartScreen no INSTALL.md).

## Privacy & security

- **Local by default.** Audio, transcripts and notes never leave your machine
  except through the LLM CLI you configure for meeting summaries (`agy` by
  default) — that one call is the only outbound path, and you choose the tool.
- Session recordings and the auth token are written owner-only.
- Dependencies are scanned continuously (cargo-audit + npm audit).
- Releases are unsigned — see INSTALL.md.

## Status

- **macOS e Windows com paridade de funcionalidade**: ditado e reuniões
  operam nos dois sistemas. Linux segue sem os motores portados.
- O tray desabilita itens de menu quando os motores estão ausentes ou
  offline, nunca trava.
- Meetings: two-channel recording ("Eu"/"Eles") dá separação de falantes de
  graça; notas roteiam pro vault por categorias definidas pelo usuário.

---

### Notas para quem for revisar este rascunho antes de publicar

- Confirmar que a seção "Status" acima reflete a realidade (não declarar
  paridade Windows até o roteiro de `voxis-verify-windows` passar
  integralmente, ditado **e** reuniões).
- Linkar para o changelog/PR real assim que existir, em vez de descrever o
  fork em prosa.
- Revisar tom: este rascunho evita detalhes de implementação de propósito —
  manter assim no README público também.
