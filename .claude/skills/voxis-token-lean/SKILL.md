---
name: voxis-token-lean
description: Regras de economia de tokens para todo o trabalho no fork Voxis-Windows (Laris + Miris). Use SEMPRE nesta sessão/projeto — antes de ler arquivos grandes, antes de disparar builds de CI, ao produzir specs/handoffs entre subagents, e ao resumir logs. Combina disciplina de comunicação telegráfica ("caveman": sem conectivo, sem repetição, sem prosa onde bastam fatos) com handoff estruturado chave:valor entre agentes ("prometheus": comprime o contexto que desce para o próximo agente em vez de reenviar prosa). Acione mesmo sem o usuário pedir explicitamente — é o modo padrão de operar neste projeto.
---

# Voxis Token-Lean

Objetivo: fazer o máximo de trabalho útil no fork Voxis-Windows com o mínimo de
tokens gastos em contexto redundante — sem perder precisão nem virar prosa
incompreensível para o usuário final. As regras abaixo valem para leitura de
código, chamadas de ferramenta, logs de CI/build e handoff entre subagents. A
resposta final ao usuário **não** vira "caveman" — continua clara e educada,
só mais enxuta.

## 0. RTK — hook global ativo, use explicitamente também

Este ambiente tem o [RTK](https://www.rtk-ai.app/) (`rtk-ai/rtk`) instalado em
`%LOCALAPPDATA%\Programs\rtk\rtk.exe` com o hook global registrado em
`~/.claude/settings.json` (`PreToolUse` → `rtk hook claude`): **todo** comando
Bash já passa pela compressão automática do RTK antes de entrar no contexto.

Mesmo assim, em todas as skills e agents deste projeto, invoque `rtk`
explicitamente na frente do comando quando ele tiver filtro dedicado — não
dependa só do hook implícito:

- `rtk git <subcomando>` (status, diff, log, commit)
- `rtk cargo <subcomando>` (build, test, check — relevante pro `tray-dev`)
- `rtk grep ...` em vez de `grep`/`rg` cru
- Para o resto (pyinstaller, gh, powershell) o hook global já comprime a
  saída; se rodar fora do hook (ex.: dentro de um subagent que abre shell
  próprio), prefixe com `rtk` mesmo assim: `rtk <comando original>`.

## 1. Leitura e busca — visar, não varrer

- Nunca `Read` um arquivo inteiro para achar uma função: `Grep` o símbolo
  primeiro, leia só a faixa relevante com `offset`/`limit`.
- Não releia um arquivo já lido nesta sessão — o harness já sabe o que foi
  lido; confie nisso.
- Prefira `Glob`/`Grep` a `ls -R`/`find` recursivo em árvores grandes
  (ex.: `packages/laris/`, `apps/tray/src-tauri/`).
- Ao investigar bug já diagnosticado num spec (ver `voxis-spec-architect`),
  vá direto ao arquivo:linha citado — não re-explore o repo do zero.

## 2. Chamadas de ferramenta — paralelizar, não repetir

- Chamadas independentes (ex.: ler 3 arquivos de owners diferentes) vão no
  mesmo turno, em paralelo — nunca sequencial quando não há dependência.
- Não repita uma chamada que já falhou por motivo determinístico (ex.: falta
  de Python real na máquina do usuário — já sabido, não tente `python --version`
  de novo "só para confirmar").

## 3. Delegação — isolar o que é volumoso

- Logs de build do PyInstaller, output de `cargo build`, ou runs do
  `tray-build.yml` são potencialmente enormes: delegue a leitura/triagem a um
  subagent (ou a um `Bash`/`gh run view --log` filtrado por `grep`) e traga de
  volta só o resumo (linhas de erro, hidden-imports faltando, DLL ausente) —
  nunca cole o log inteiro no contexto principal.
- Cada subagent de domínio (`laris-engine-dev`, `miris-windows-dev`,
  `tray-dev`) trabalha isolado no seu diretório — não precisa carregar o
  contexto dos outros dois.

## 4. Comunicação — telegráfico entre agentes, claro com o usuário

Inspirado em estilo "caveman" para tudo que é **interno** (notas de handoff,
comentários de progresso entre subagents, rascunhos de spec):

- Sujeito + verbo + objeto. Sem conectivos decorativos, sem "cabe destacar
  que", sem repetir o que o outro agente já escreveu.
- Fatos primeiro, justificativa só se não for óbvia.

Isso **não** se aplica ao texto final que o usuário lê — esse continua em
português claro, cortês, 1-2 frases de resumo por turno, como já é o padrão
desta sessão.

## 5. Handoff estruturado ("bloco prometheus")

Ao passar trabalho de `voxis-spec-architect` para um subagent de domínio, ou
entre subagents, use bloco chave:valor compacto em vez de prosa — o agente
receptor não deve precisar reprocessar parágrafos para extrair o que fazer:

```
owner: laris-engine-dev
arquivo: packages/laris/packaging/laris.spec
linha: 32
ação: pathex=[".."] -> pathex=[str(Path(SPECPATH).parent)]
critério_aceite: `import laris` resolve; dist/laris-engine roda sem ModuleNotFoundError
depende_de: nenhum
```

Isso vale para specs inteiros também: a seção "Tarefas por owner" de um SDD
(ver skill/agent de spec) deve ser blocos assim, um por item, não parágrafos
narrativos.

## 6. Specs e memória como fonte de verdade

- Se já existe um SDD (`docs/superpowers/plans/*.md`) ou uma memória
  persistida cobrindo a decisão, cite-a e reuse — não rederive o raciocínio.
- Ao encontrar uma decisão nova e não-óbvia que vai se repetir (ex.: "no
  Windows sempre matar o processo direto, sem esperar 3s"), isso é candidato a
  memória de feedback/projeto — não repita a explicação em toda sessão futura.

## 7. Logs de CI/build — grep, não cole

- `rtk gh run view --log <run-id>` (ou, sem filtro dedicado,
  `gh run view --log <run-id> | rtk grep -iE "error|warning|missing module|traceback"`):
  sempre filtre antes de trazer para o contexto. Nunca cole um log de build
  completo.
- Ao iterar em falha de hidden-import do PyInstaller, cole só a linha do
  `ModuleNotFoundError`/`WARNING: Hidden import` relevante, não o log inteiro
  do `Analysis`.
