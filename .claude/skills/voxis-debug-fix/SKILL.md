---
name: voxis-debug-fix
description: Método de debugging, correção e melhoria de qualidade de código no fork Voxis-Windows (Python do Laris/Miris, Rust/Tauri do tray, TypeScript da UI). Use SEMPRE que algo não funcionar como esperado — engine que não sobe, hotkey morto, orb que não aparece, gravação sem áudio, teste vermelho, build quebrado — e também ao revisar código recém-escrito por um subagent antes de dar por fechado. Cobre reprodução antes de teoria, as armadilhas de falha silenciosa específicas deste app, e o checklist de qualidade por camada. Acione mesmo sem o usuário pedir "debug" explicitamente: "não funciona", "não acontece nada", "travou", "sumiu" são gatilhos.
---

# Voxis Debug & Fix

Aplique [[voxis-token-lean]] o tempo todo: prefixe `rtk` nos comandos com
filtro dedicado (`rtk git`, `rtk cargo`, `rtk grep`, `rtk pytest`), leia
trechos visados em vez de arquivos inteiros, e nunca cole log de build
completo no contexto.

## Regra zero: reproduza antes de teorizar

Não proponha causa sem ter observado o sintoma. Ordem obrigatória:

1. **Observe** — rode o fluxo quebrado, leia o log, veja o estado no disco.
2. **Isole** — qual camada? (engine Python / tray Rust / UI TS / packaging)
3. **Confirme a causa** — prove com evidência, não com plausibilidade.
4. **Só então** edite código.

Um "provavelmente é X" sem evidência custa mais tokens e mais tempo do que os
dois comandos que teriam confirmado. Este projeto já teve **um** bug de
packaging explicando 100% dos sintomas — a tentação de teorizar em cima de
sintomas múltiplos é exatamente o erro a evitar.

## Armadilha nº 1 deste app: falha silenciosa

O `laris-engine.exe` (e o `miris-engine.exe`) são empacotados **windowed**
(`console=False`). Quando o processo morre no boot, **não há janela, não há
stderr no terminal, não há popup** — o tray simplesmente mostra tudo
desligado. Sintomas totalmente distintos (hotkey morto, orb ausente, toggle
que não fica ligado, "ditado offline") são, quase sempre, o mesmo processo
morrendo em silêncio.

**Primeiro comando de qualquer investigação de ditado/reunião:**

```bash
rtk grep -iE "traceback|error|modulenotfound|importerror" ~/.config/voice-at/laris-engine.log
```

Estado no disco que prova se o daemon subiu de verdade:

| Arquivo | Significa |
|---|---|
| `~/.config/voice-at/laris-engine.log` | traceback aqui ⇒ engine morreu no boot |
| `~/.config/voice-at/peers.json` | existe + porta viva ⇒ daemon subiu |
| `~/.config/voice-at/laris-settings.json` | o que a UI realmente persistiu |
| `%LOCALAPPDATA%\VOXIS\engine\_internal\laris\` | o pacote foi bundlado (fix A1) |

Se o log tem traceback, **pare aqui**: o bug é no engine ou no packaging, não
na UI, não no hotkey, não no orb. Não investigue as camadas de cima.

## Debug por camada

### Engine Python (`packages/laris/`, `packages/miris/`)

Há Python 3.11 real nesta máquina — use-o, não espere CI para tudo:

```bash
rtk python -m pytest packages/miris/tests/ -x -q      # falha rápido
rtk python -c "import laris.platform.windows"          # import isolado
```

- **`ModuleNotFoundError` só no exe congelado, nunca no venv** ⇒ é
  packaging (`.spec`: `pathex`, `hiddenimports`, `collect_submodules`), não
  código. Ver [[voxis-build-windows]].
- **Import lazy** — imports pyobjc/mlx vivem dentro de funções de propósito.
  Ao mover um import para o topo você quebra o Windows silenciosamente.
  Nunca "limpe" um import lazy sem checar a plataforma.
- Ao mexer em áudio, valide o WAV de verdade: sample rate, canais, duração
  não-zero. "O arquivo existe" não é evidência de que gravou.

### Tray Rust (`apps/tray/src-tauri/`)

```bash
rtk cargo check --manifest-path apps/tray/src-tauri/Cargo.toml
rtk cargo test  --manifest-path apps/tray/src-tauri/Cargo.toml
```

- Código sob `#[cfg(windows)]` **não é compilado** em outras plataformas —
  erro de digitação lá só aparece no build Windows. Sempre rode o `check` de
  verdade, não confie em leitura.
- Contrato com o Python é por arquivo e por processo, não por API: se mudar
  nome de chave, path de binário ou formato de `peers.json`, os dois lados
  precisam mudar juntos. Chave nova em `KNOWN_LARIS_KEYS` sem o par em
  `laris/settings.py::KNOWN_KEYS` (ou vice-versa) = setting que "salva" e
  some.

### UI TypeScript (`apps/tray/src/main.ts`)

- Fallbacks precisam ser por plataforma. `cmd_r` como default no Windows foi
  exatamente esse tipo de bug — o valor existe, é aceito, e simplesmente
  nunca dispara.
- Um campo que salva uma chave que o backend não lê é pior que um campo
  ausente: o usuário muda, vê persistir, e nada acontece.

## Correção: ataque a causa, não o sintoma

- Se o fix é `try/except` em volta do erro, provavelmente é sintoma. Pergunte
  o que fez o erro acontecer.
- **Nunca** silencie erro em código de produção. Este app já sofre de
  diagnóstico difícil por causa do modo windowed — um `except: pass` a mais
  custa horas depois. Erro deve ir para o log com contexto suficiente para
  alguém entender em 6 meses.
- Não conserte teste desabilitando teste. Se o teste ficou obsoleto por
  mudança deliberada de contrato, **reescreva-o para o novo contrato** e diga
  isso explicitamente — não delete.
- Um fix por commit, com mensagem que diz o *porquê*. Sem `Co-Authored-By`
  (ver memória do projeto).

## Qualidade: o que revisar antes de fechar

Antes de dar uma tarefa por concluída — sua ou de um subagent:

- [ ] O caminho macOS continua intacto? (todo `#[cfg(windows)]` /
      `if platform` tem o outro lado preservado)
- [ ] Erros são logados com contexto, ou algum caminho falha em silêncio?
- [ ] Chaves/paths/formatos compartilhados entre Rust e Python batem dos dois
      lados?
- [ ] Testes: passam? algum ficou vermelho "de propósito" e não foi reescrito?
- [ ] Dependência nova entrou em `requirements-windows.txt` **e** no `.spec`
      (`collect_all`/`hiddenimports`)? Dep que falta só aparece no exe
      congelado, nunca no venv.
- [ ] Artefato de trabalho (notas `*_SUMMARY.md`, `TESTING_*.md`) foi parar na
      raiz do repo? Isso é lixo de processo — move para `docs/` ou apague
      antes do repo virar público.
- [ ] Risco conhecido e não validado ficou **registrado** no SDD em
      `docs/superpowers/plans/`, em vez de esquecido?

Para revisão mais profunda de um diff, delegue a `/code-review`; para
limpeza de estilo/duplicação sem caça a bug, `/simplify`. Esta skill é o
método; aquelas são as ferramentas.

## Fechamento

Nenhum fix está "pronto" por ter compilado. Está pronto quando o
comportamento foi observado funcionando:

- Mudança em engine/packaging ⇒ [[voxis-build-windows]] e depois
  [[voxis-verify-windows]].
- Mudança só em Rust/TS ⇒ `rtk cargo check` + o item correspondente do
  roteiro de verificação.

Ao reportar: diga o que passou, o que falhou e o que **não** foi verificado.
Nunca declare verificado o que não foi executado.
