---
name: voxis-build-windows
description: Loop de build do fork voxis-windows (Laris + Miris). Use sempre que for preciso compilar/testar o `laris.spec` ou `miris.spec`, empacotar com PyInstaller, disparar o `windows.yml` no runner windows-latest, ou stagear artefatos em `engine/`/`engine-miris/`. Acione também ao iterar em erro de hidden-import ou DLL faltando no PyInstaller.
---

# Voxis Build (Windows)

Aplique [[voxis-token-lean]] durante todo este fluxo: filtre logs, não os cole
inteiros. Prefixe com `rtk` todo comando abaixo que tenha filtro dedicado
(`rtk git`, `rtk cargo`, `rtk gh`) — o hook global do RTK já comprime o resto,
mas invoque explícito mesmo assim.

## Contrato de output esperado

- `packages/laris/dist/laris-engine/` (onedir) → staged em
  `apps/tray/src-tauri/engine/` como `laris-engine.exe` + `_internal/`.
- `packages/miris/dist/miris-engine/` (onedir) → staged em
  `apps/tray/src-tauri/engine-miris/`.
- Artefato final: `apps/tray/src-tauri/target/release/bundle/{msi,nsis}/*`.

## Loop local

A máquina tem Python 3.11 (`py -3.11`) e `cargo`. Os venvs `.venv-debug`
(laris) e `.venv-miris` (miris) na raiz do repo têm os dois pacotes
instalados em modo editável.

1. Testes antes de tudo (de `packages/laris` e de `packages/miris`):
   `PYTHONPATH=../../.github/scripts python -m pytest -q -p pytest_windows_skips --ignore-glob="*_linux*"`
2. Os specs exigem `packages/laris/assets/silero_vad.onnx` e
   `packages/<pkg>/whispercpp/` (binários do whisper.cpp): sem eles, o
   `pyinstaller` falha de propósito. Baixe o modelo pelo mesmo URL do
   `windows.yml`; os binários vêm de um artefato do CI ou do build local.
3. `rtk pyinstaller packaging/laris.spec --noconfirm` (idem `miris.spec`).
4. Conferir `dist/laris-engine/laris-engine.exe` e que o pacote `laris` está
   no PYZ (**não** existe `_internal/laris/` — Python puro é arquivado dentro
   do exe; ver [[voxis-debug-fix]] para o comando de inspeção do PYZ).
5. Copiar `dist/laris-engine/*` por cima de `%LOCALAPPDATA%\VOXIS\engine\`
   para provar o fix sem esperar o CI.

## Loop via CI (instalador completo)

1. Commit no fork (`origin` = `hallygtree/voxis-windows`; o Actions roda na
   conta do fork, não no upstream).
2. Disparar o `windows.yml`: todo push e PR roda os testes; o instalador sai em
   - tag: `rtk git tag v<x.y.z>-rc<n> && rtk git push origin v<x.y.z>-rc<n>`, ou
   - manual: `rtk gh workflow run windows.yml --ref <branch>`.
3. Acompanhar: `rtk gh run watch` (ou `rtk gh run list --workflow=windows.yml --limit 1`).
4. Em falha, só a parte relevante do log:
   `rtk gh run view <run-id> --log-failed | rtk grep -iE "error|missing module|traceback|hidden import"`
5. Iterar no `.spec`/workflow e redisparar até sair verde com
   `bundle/{msi,nsis}/*`.
6. Baixar o artefato (runs manuais): `rtk gh run download <run-id> -n voxis-windows`.

## Erros comuns de PyInstaller a esperar

- `ModuleNotFoundError` em runtime com exit silencioso (`console=False`) —
  sintoma do bug A1 (pathex errado); olhar sempre `pathex` e
  `collect_submodules` primeiro.
- Hidden import faltando de dependência lazy (`laris.platform.windows`,
  `laris.stt_whispercpp`, `miris.systemtap_windows`, etc.) — resolvido por
  `hiddenimports += collect_submodules("laris")` (e `"miris"`).
- DLL de runtime (`onnxruntime`, `soundcard`) ausente do bundle — conferir
  o `collect_all` do spec, não assumir que o PyInstaller pega sozinho.

Após build verde, sempre encaminhar para a skill [[voxis-verify-windows]]
antes de considerar o fix validado.
