# SDD-A2/A3 — Laris polish: encerramento gracioso (Win) + settings coerentes

owner: laris-engine-dev (Python) + tray-dev (Rust/TS)
status: pronto para implementar
depende_de: SDD-A1 (o engine precisa subir para validar ponta a ponta)

## Contexto

Com o A1 corrigido, o ditado sobe, mas duas arestas ficam. (A2) `LarisDaemon::stop`
só tem caminho `#[cfg(unix)]` (SIGTERM); no Windows cai no fallback de 30×100ms →
**3s de congelamento** do tray a cada toggle-off / troca de setting / quit. (A3) A UI
de settings mostra defaults macOS: fallback de `DICTATE_KEY` é `"cmd_r"` (inexistente
no Windows) e o campo de modelo persiste `STT_MODEL` (id mlx) que o
`FasterWhisperTranscriber` **ignora** — ele lê `STT_MODEL_FASTER`, que hoje nem
sequer é aceito por `settings.py::KNOWN_KEYS` nem pelo validador do tray.

## Objetivo / Não-objetivo

- Objetivo: remover o freeze de 3s no Windows e alinhar a UI de settings ao backend
  faster-whisper (tecla certa, modelo certo, persistência aceita ponta a ponta).
- Não-objetivo: live-reload de settings (segue fora de escopo — o tray reinicia o
  daemon), `CTRL_BREAK` teardown elaborado, mudança de defaults de config.py.

## Requisitos

1. No Windows, `LarisDaemon::stop` encerra o engine imediatamente, sem o loop de 3s.
2. O caminho unix (SIGTERM + grace) permanece inalterado.
3. `laris/settings.py::KNOWN_KEYS` aceita `STT_MODEL_FASTER`.
4. O validador do tray (`commands.rs::KNOWN_LARIS_KEYS` + `valid_value`) aceita e
   valida `STT_MODEL_FASTER`.
5. Na UI, o fallback de `DICTATE_KEY` no Windows é `shift_r`, não `cmd_r`.
6. Na UI, o campo de modelo no Windows persiste `STT_MODEL_FASTER` (valores tipo
   `small`/`base`/`medium`), não o id mlx `STT_MODEL`.
7. `docs/INSTALL.md` reflete o modelo faster-whisper (`small`, download no 1º uso,
   CPU int8).

## Design

A2: caminho `#[cfg(windows)]` que faz `child.kill()` + `child.wait()` imediato. O
engine congelado (onedir) não tem estado a flushar além do `peers.json`, e o probe
TCP do tray já trata porta-caída como offline, então kill imediato é seguro e mata o
freeze. `CTRL_BREAK_EVENT` (exigiria `CREATE_NEW_PROCESS_GROUP` no spawn) foi
considerado para teardown limpo do listener pynput mas descartado: complexidade sem
ganho observável (o processo morre e o SO libera o hook).

A3: `STT_MODEL_FASTER` já é lido por `config.py` (default `small`) — só falta o
gate de aceitação em `settings.py` e no tray, mais o ajuste de UI. Decisão de UX:
manter um único campo de modelo, mas no Windows ligá-lo a `STT_MODEL_FASTER`
(nomes de tamanho) em vez de esconder — usuário Windows ainda quer trocar
small↔base. Fallback de tecla passa a ser plataforma-condicional no TS/validação.

Alternativas descartadas:
- Esconder o campo de modelo no Windows: mais simples, mas remove controle útil de
  latência/qualidade. Rejeitada.
- Mapear `STT_MODEL` mlx→size no backend: acopla dois ids, frágil. Rejeitada em
  favor de persistir a chave que o backend já lê.

## Tarefas por item

```
owner: laris-engine-dev
arquivo: packages/laris/laris/settings.py
ação: adicionar "STT_MODEL_FASTER" à tupla KNOWN_KEYS
critério_aceite: um laris-settings.json com STT_MODEL_FASTER="base" é carregado por load_settings() (hoje é filtrado fora); config.STT_MODEL_FASTER passa a refletir o arquivo
depende_de: nenhum
```

```
owner: laris-engine-dev
arquivo: docs/INSTALL.md
ação: alinhar a nota de modelo Windows: faster-whisper size name (small), download no primeiro uso, expectativa CPU int8; remover/ajustar menção ao id mlx no contexto Windows
critério_aceite: seção Windows menciona STT_MODEL_FASTER=small e não induz o usuário a setar id mlx
depende_de: nenhum
```

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/laris.rs
ação: em LarisDaemon::stop, adicionar bloco `#[cfg(windows)]` que faz child.kill()+child.wait() imediato e retorna, mantendo o `#[cfg(unix)]` SIGTERM+grace loop intacto para unix
critério_aceite: toggle-off/quit no Windows não bloqueia 3s; teste Rust cross-plat continua verde (o teste unix-only de lifecycle não regride)
depende_de: nenhum
```

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/commands.rs
ação: adicionar "STT_MODEL_FASTER" a KNOWN_LARIS_KEYS (ampliar array e tamanho); em valid_value, aceitar STT_MODEL_FASTER com regra !s.trim().is_empty() (ou allowlist small|base|medium|large-v3 etc)
critério_aceite: save_laris_settings aceita {"STT_MODEL_FASTER":"base"} e rejeita "" ; unknown-key guard não barra a chave nova
depende_de: nenhum
```

```
owner: tray-dev
arquivo: apps/tray/src/main.ts
ação: fallback de #dictate-key passa a shift_r quando a plataforma é Windows (detectar via navigator/OS ou expor flag do backend); no save de laris, no Windows persistir STT_MODEL_FASTER a partir do campo de modelo em vez de STT_MODEL; ao carregar, ler s.laris.STT_MODEL_FASTER com default "small"
critério_aceite: numa instalação Windows a UI mostra shift_r selecionado por padrão e salva STT_MODEL_FASTER=<size>; o payload não envia STT_MODEL no Windows
depende_de: commands.rs aceitar STT_MODEL_FASTER
```

## Critérios de aceite (voxis-verify-windows / prova local)

- Toggle de ditado off e "Sair" no tray retornam sem congelamento perceptível
  (< ~300ms), no Windows.
- Salvar modelo `base` na UI escreve `STT_MODEL_FASTER":"base"` em
  `~/.config/voice-at/laris-settings.json`; reiniciar o daemon e conferir no
  `laris-engine.log` que o modelo carregado é `base` (não `small`).
- UI de settings numa máquina Windows exibe `shift_r` como tecla default.
- Ditado funciona com a tecla default sem o usuário ter que trocar.

## Riscos

- Kill imediato no Windows: se algum dia o engine passar a ter estado não-flushado,
  reavaliar CTRL_BREAK. Hoje não há.
- Detecção de plataforma no TS: a webview do tray não expõe `process.platform`
  trivialmente — pode ser preciso o backend injetar a plataforma no payload de
  `get_settings` (campo `os`) em vez de heurística `navigator.userAgent`. Preferir
  o campo do backend para determinismo.
- Coexistência de STT_MODEL (mlx) e STT_MODEL_FASTER no mesmo arquivo: ambos podem
  persistir; garantir que a UI Windows não sobrescreva/apague o STT_MODEL de um
  usuário que sincroniza settings entre mac e Windows.
