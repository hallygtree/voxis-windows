---
name: voxis-build-windows
description: Loop de build do fork Voxis-Windows (Laris + Miris) via CI, já que a máquina local não tem Python real nem Rust/cargo. Use sempre que for preciso compilar/testar o `laris.spec` ou `miris.spec`, empacotar com PyInstaller, disparar o `tray-build.yml` no runner windows-latest, ou stagear artefatos em `engine/`/`engine-miris/`. Acione também ao iterar em erro de hidden-import ou DLL faltando no PyInstaller.
---

# Voxis Build (Windows)

Aplique [[voxis-token-lean]] durante todo este fluxo: filtre logs, não os cole
inteiros. Prefixe com `rtk` todo comando abaixo que tenha filtro dedicado
(`rtk git`, `rtk cargo`, `rtk gh`) — o hook global do RTK já comprime o resto,
mas invoque explícito mesmo assim.

## Contrato de output esperado

- `packages/laris/dist/laris-engine/` (onedir) → staged em
  `apps/tray/src-tauri/engine/` como `laris-engine.exe` + `_internal/`.
- `packages/miris/dist/miris-engine/` (quando existir, ver B-tasks do Miris) →
  staged em `apps/tray/src-tauri/engine-miris/`.
- Artefato final: `apps/tray/src-tauri/target/release/bundle/{msi,nsis}/*`.

## Loop local (só se o usuário tiver Python 3.11 instalado)

1. `cd packages/laris && python -m venv .venv && rtk .venv\Scripts\pip install -e . -r requirements.txt pyinstaller`
2. `rtk pyinstaller packaging/laris.spec --noconfirm`
3. Conferir `dist/laris-engine/laris-engine.exe` + `_internal/laris/` existe
   (prova do fix A1 — hoje falta `laris/` no bundle).
4. Copiar `dist/laris-engine/*` por cima de
   `%LOCALAPPDATA%\VOXIS\engine\` para provar o fix sem esperar CI.
5. Repetir para `packages/miris/packaging/miris.spec` quando existir.

## Loop via CI (caminho principal — máquina do usuário não tem toolchain)

1. Commit dos fixes no fork do usuário (precisa ser o remoto dele — Actions
   roda na conta dele, não no upstream): `rtk git commit -m "..."`.
2. Disparar o workflow:
   - Tag: `rtk git tag v0.x.y-rc<n> && rtk git push origin v0.x.y-rc<n>`, ou
   - Manual: `rtk gh workflow run tray-build.yml --ref <branch>`
3. Acompanhar: `rtk gh run watch` (ou `rtk gh run list --workflow=tray-build.yml
   --limit 1` para pegar o run id).
4. Em falha, buscar só a parte relevante do log:
   `rtk gh run view <run-id> --log-failed | rtk grep -iE "error|missing module|traceback|hidden import"`
5. Iterar no `.spec`/workflow, re-disparar. Repita até `windows-latest` sair
   verde com `bundle/{msi,nsis}/*` publicado.
6. Baixar artefato: `rtk gh run download <run-id> -n <nome-do-artefato>`.

## Erros comuns de PyInstaller a esperar

- `ModuleNotFoundError` em runtime com exit silencioso (`console=False`) —
  sintoma do bug A1 (pathex errado); olhar sempre `pathex` e
  `collect_submodules` primeiro.
- Hidden import faltando de dependência lazy (`laris.platform.windows`,
  `laris.stt_faster`, etc.) — resolvido por
  `hiddenimports += collect_submodules("laris")`.
- DLL de runtime (`onnxruntime`, `ctranslate2`) ausente do bundle — conferir
  `datas`/`binaries` do spec, não assumir que o PyInstaller pega sozinho.

Após build verde, sempre encaminhar para a skill [[voxis-verify-windows]]
antes de considerar o fix validado.
