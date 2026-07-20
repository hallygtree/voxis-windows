# SDD-A1 — Laris packaging: empacotar o pacote `laris` (destrava o ditado)

owner: laris-engine-dev
status: pronto para implementar
depende_de: nenhum

## Contexto

Num Windows 11 limpo, `laris-engine.exe` morre no boot com `ModuleNotFoundError:
No module named 'laris'`. O bundle onedir tem todas as deps nativas e o `frontend/`,
mas **não** contém o pacote `laris`. Causa: em `packaging/laris.spec` o `pathex=[".."]`
resolve para `packages/` (o build roda de `packages/laris`), diretório que não
contém `laris/`. PyInstaller emite só um warning e gera um exe quebrado. Como o exe
é windowed (`console=False`), o crash é silencioso: sem daemon → sem `peers.json` →
tray offline, hotkeys mortos, orb nunca abre. Bug único que explica 100% dos sintomas.

## Objetivo / Não-objetivo

- Objetivo: fazer `import laris` resolver na análise e garantir que todos os
  submódulos lazy entrem no bundle, de modo que o exe congelado suba o daemon.
- Não-objetivo: mudar backend Windows, UI de settings (A3), encerramento (A2),
  ou qualquer coisa de Miris. Nada de assinatura de código.

## Requisitos

1. `pathex` do `Analysis` aponta para o diretório que **contém** o pacote `laris`
   (`packages/laris`), não para `packages/`.
2. `collect_submodules("laris")` é adicionado aos `hiddenimports`, cobrindo os
   submódulos que a análise estática não enxerga (`laris.platform.windows`,
   `laris.stt_faster`, `laris.hotkey`, `laris.audio_capture`,
   `laris.dictation_windows`, `laris.peer_client`, `laris.state_machine`,
   `laris.server`, ...).
3. `collect_submodules("laris")` roda em tempo de spec com `laris` importável.
4. O CI instala o pacote `laris` no ambiente de build antes do PyInstaller
   (belt-and-suspenders com o `pathex`), sem arrastar deps novas.
5. O bundle resultante contém `laris/` (verificável no `dist/laris-engine/`).

## Design

Abordagem: corrigir o `pathex` para o path absoluto do diretório do spec-pai e
reforçar com `collect_submodules` + `pip install -e .` no CI.

- `pathex=[str(Path(SPECPATH).parent)]` — `SPECPATH` é `packages/laris/packaging`,
  logo `.parent` = `packages/laris`. Determinístico, independe do CWD do build.
- `sys.path.insert(0, str(Path(SPECPATH).parent))` no topo do spec — necessário
  porque `collect_submodules("laris")` importa `laris` em tempo de spec.
- `pip install -e .` de `packages/laris`: `pyproject.toml` **não declara
  `dependencies`** (confirmado), então instala só o pacote `laris`, dep-free,
  tornando `import laris` resolvível sem poluir o bundle.

Alternativas descartadas:
- Só `pip install -e .` sem corrigir `pathex`: funciona no CI mas deixa o spec
  frágil para builds locais fora do venv. Rejeitada — corrige o sintoma, não a causa.
- Listar cada submódulo `laris.*` à mão nos `hiddenimports`: quebra a cada novo
  módulo. `collect_submodules` é auto-mantido.
- `pathex` relativo (`"laris"`, `"."`): depende do CWD do runner; o bug atual é
  exatamente essa fragilidade. Path absoluto via `SPECPATH` elimina.

## Tarefas por item

```
owner: laris-engine-dev
arquivo: packages/laris/packaging/laris.spec
ação: inserir no topo (após imports) `import sys` + `sys.path.insert(0, str(Path(SPECPATH).parent))`; trocar `pathex=[".."]` por `pathex=[str(Path(SPECPATH).parent)]`; adicionar `hiddenimports += collect_submodules("laris")` junto aos demais hiddenimports (collect_submodules já é importado na linha 4)
critério_aceite: `pyinstaller packaging/laris.spec --noconfirm` roda sem warning "module named 'laris' not found"; `dist/laris-engine/` contém o pacote laris (arquivos laris/*.pyc no bundle)
depende_de: nenhum
```

```
owner: laris-engine-dev
arquivo: .github/workflows/tray-build.yml
ação: no passo "Build frozen laris engine (Windows)" (working-directory packages/laris), adicionar `pip install -e .` entre `pip install -r requirements-windows.txt pyinstaller` e a chamada `pyinstaller packaging/laris.spec`
critério_aceite: job windows-latest instala o pacote laris sem puxar deps extras (pyproject sem `dependencies`); build produz bundle sem o ModuleNotFoundError
depende_de: nenhum
```

## Critérios de aceite (voxis-verify-windows / prova local)

- No bundle staged (`apps/tray/src-tauri/engine/` ou `dist/laris-engine/`), o
  diretório `laris/` existe com os submódulos.
- Rodar o `laris-engine.exe` congelado num Windows limpo: `laris-engine.log`
  **não** contém `ModuleNotFoundError: No module named 'laris'` nem traceback.
- `peers.json` é escrito em `~/.config/voice-at/` após o boot (prova de que o
  daemon subiu).
- Prova rápida local (sem CI, se houver Python 3.11): rebuild só do laris-engine e
  copiar `dist/laris-engine/*` por cima de `AppData\Local\VOXIS\engine\`; segurar
  Right-Shift e ditar.

## Riscos

- `collect_submodules("laris")` pode arrastar submódulos macOS-only por import
  lazy — mitigado pelos `excludes` já presentes no spec (torch/mlx/pyobjc). Se um
  submódulo novo importar pyobjc no topo, ajustar excludes.
- `pip install -e .` em modo editável pode não empacotar bem se o CWD do
  PyInstaller mudar; o `pathex` absoluto é a rede de segurança.
- Warning→erro: confirmar que PyInstaller 6.x não trata o import ausente como
  fatal ao ponto de abortar (hoje só warna); se abortar, é sinal de que o fix é
  ainda mais necessário.
