# SDD-P0-ENGINE — rect top-left, estado do orb e `ready` no engine Laris

owner: laris-engine-dev
status: pronto para implementar
contrato: **SDD-C0** (`docs/superpowers/plans/2026-07-21-orb-parity-c0-contracts.md`).
Payloads e semântica saem de lá, não daqui.
depende_de: nenhum (é a base das outras fases)
bloqueia: SDD-P1-TRAY (consome os dois endpoints e o indicador de "carregando modelo")

## Contexto

No macOS o engine Python é dono da janela do orb: um `NSPanel` dimensionado e posicionado
por `orb_theme.position_rect()`, mostrado e escondido a cada ditado. No Windows quem cria a
janela é o tray Rust, e o engine devolve um `_NoOpOverlay` (`platform/windows.py:10-20`)
cujo `show`/`hide` não fazem nada. O tray, sem nenhuma fonte de verdade sobre tamanho,
posição ou fase, mantém a janela aberta enquanto `laris_alive` for verdadeiro.

Consequência dupla: o seletor de posição do menu salva no `orb-theme.json` e **nunca teve
consumidor no Windows** (`position_rect()` só é lido por `overlay_app.py`, macOS-only), e
uma janela transparente always-on-top anima 24h por dia para um recurso usado ~1% do tempo.

Esta fase entrega o que falta do lado Python — e é a fase que **roda inteira nesta máquina**,
com pytest, sem depender do CI.

## Objetivo / Não-objetivo

- Objetivo: expor o retângulo do orb em coordenadas top-left via `/theme`, publicar o estado
  de visibilidade/prontidão via `/overlay/state`, e fazer o backend Windows escrever nesse
  estado a partir dos `overlay.show()`/`hide()` que o `daemon.py` já emite.
- Não-objetivo: Rust, CSS, JS do orb, e qualquer mudança no caminho macOS. `overlay_app.py`
  e `platform/macos.py` não são tocados. Nenhuma mudança em `daemon.py` além de sinalizar
  `ready` e repassar o objeto de estado.

## Requisitos

1. `orb_theme.position_rect_topleft(theme, screen_w, screen_h)` devolve `(x, y, w, h)` com
   origem no canto superior esquerdo, **reutilizando** `position_rect()` — sem reescrever a
   lógica e sem duplicar `_TOP_MARGIN`/`_EDGE_MARGIN`.
2. `GET /theme` aceita `screen_w`/`screen_h` opcionais e, quando ambos válidos, acrescenta
   `rect` conforme SDD-C0 §C1. Sem eles, a resposta é idêntica à atual (chave `rect`
   ausente, não `null`).
3. Novo módulo `laris/orb_state.py` com um objeto que guarda `visible`, `ready`, `mode` e um
   `serial` incremental, com `threading.Event` para acordar quem espera.
4. O objeto de estado é **injetado**, como o `voice_queue` já é: criado no `__main__.py`,
   passado a `build_app(...)` e ao caminho do backend de plataforma. **Não** existe singleton
   de módulo — `server.py` é uma factory e seu docstring proíbe globals de módulo
   explicitamente.
5. `GET /overlay/state` implementa SDD-C0 §C2, incluindo o clamp de 25s e o bloqueio fora do
   event loop.
6. `platform/windows.py` troca `_NoOpOverlay` por um overlay que escreve no estado:
   `show(mode)` marca `visible=True, mode=mode`; `hide()` marca `visible=False, mode=None`.
7. Quando não há objeto de estado injetado (uso standalone/teste), o backend continua
   funcionando — degrada para no-op, nunca levanta.
8. `daemon.py` marca `ready = True` logo após `backend.warm()` (`:140`), quando houver estado.
9. O caminho macOS não observa nenhuma mudança de comportamento.

## Design

**Coordenadas (0.1).** A função irmã reutiliza a existente e inverte o eixo:

```python
def position_rect_topleft(theme, screen_w, screen_h):
    """(x, y, w, h) com origem no canto SUPERIOR esquerdo (Win32/Tauri)."""
    x, y_bottom = position_rect(theme, screen_w, screen_h)
    size = float(theme["size"])
    return x, screen_h - y_bottom - size, size, size
```

**`/theme` (0.2).** Dois parâmetros `float | None`. O `rect` só entra quando ambos são
verdadeiros e positivos; a montagem do dicionário de resposta continua a mesma nos demais
casos. Ver SDD-C0 §C1, itens 2 e 4-10.

**Estado do orb (0.3).** Uma classe pequena, thread-safe, com `threading.Lock` para as
mutações e um `threading.Event` que é `set()` a cada mudança e limpo pelos waiters. Forma
sugerida (nomes são contrato interno, não HTTP):

- `snapshot() -> dict` — `{"visible", "ready", "mode", "serial"}`, coerente (sob lock).
- `show(mode)` / `hide()` / `set_ready(True)` — mutações que incrementam `serial` **apenas
  quando o valor muda de fato** (evita acordar o cliente à toa).
- `wait_for_change(since, timeout) -> dict` — bloqueante, chamado via `asyncio.to_thread`;
  retorna imediatamente se `serial != since`.

O `serial` começa em 1 (SDD-C0 §18) para que `since=0` sempre retorne na hora.

**Injeção (req. 4).** `build_app(token, voice_queue=None, orb_state=None)` guarda em
`app.state.orb_state`; um `orb_state=None` cria uma instância nova e desconectada, exatamente
o padrão já usado para `voice_queue`. O `__main__.py` cria **uma** instância e a passa tanto
para `build_app` quanto para `daemon.run(...)`, que a repassa ao backend na criação do
overlay. Isso exige alargar `PlatformBackend.make_overlay` para aceitar o estado como
argumento opcional (`make_overlay(url, state=None)`) em `platform/base.py`, `macos.py`
(ignora) e `windows.py` (usa). Alternativa considerada e descartada: um setter separado
`backend.set_orb_state()` — mais superfície e um estado meio-construído entre as chamadas.

**`ready` (0.3, alimenta a Fase 3 do tray).** O uvicorn sobe **antes** do `backend.warm()`,
então `laris_alive` mente: hoje o tray abre o orb e a tecla não responde. Marcar `ready` logo
depois do `warm()` alimenta de graça o indicador "carregando modelo" do tray, que ficou muito
mais visível agora que o modelo é Whisper `large` em CPU int8.

**Alternativas descartadas** (as três de desenho do estado — assinar o WS, API Tauri no JS,
long-poll) estão registradas em SDD-C0 §Design e não são repetidas aqui.

## Tarefas por owner

```
owner: laris-engine-dev
arquivo: packages/laris/laris/orb_theme.py
ação: adicionar position_rect_topleft(theme, screen_w, screen_h) -> (x, y, w, h) reutilizando position_rect(); não duplicar _TOP_MARGIN/_EDGE_MARGIN nem reescrever o cálculo
critério_aceite: pytest local — para cada posição não-custom, y_topleft + y_bottomleft + size == screen_h; com 1920x1080 e o tema default, (865.0, 445.0, 190.0, 190.0); top-left -> x=16.0, y=40.0; custom [x,y] converte com y = screen_h - custom[1] - size
depende_de: nenhum
```

```
owner: laris-engine-dev
arquivo: packages/laris/laris/orb_state.py (novo)
ação: criar o objeto de estado do orb (visible/ready/mode/serial) com lock + threading.Event; API snapshot(), show(mode), hide(), set_ready(bool), wait_for_change(since, timeout); serial começa em 1 e só incrementa quando (visible, ready, mode) muda de fato; sem estado de módulo — tudo é instância, e o docstring registra por quê
critério_aceite: pytest local — serial inicial >= 1; show() incrementa; show() com o mesmo mode não incrementa; wait_for_change(serial_atual, 0.3) expira em ~0.3s devolvendo o mesmo serial; wait_for_change acordado por show() de outra thread retorna em <50ms com o serial novo
depende_de: nenhum
```

```
owner: laris-engine-dev
arquivo: packages/laris/laris/server.py
ação: (a) build_app ganha o parâmetro orb_state=None, guardado em app.state.orb_state com o mesmo padrão de fallback do voice_queue; (b) GET /theme ganha screen_w/screen_h opcionais e a chave rect conforme SDD-C0 §C1; (c) novo GET /overlay/state?token&since&wait conforme SDD-C0 §C2, com clamp de wait em [0,25] e o bloqueio via asyncio.to_thread — nunca no event loop
critério_aceite: todos os itens da seção "Critérios de aceite" do SDD-C0 passam via TestClient; /theme sem os params não tem a chave rect; /overlay/state sem token válido retorna 403; nenhum global de módulo novo foi introduzido
depende_de: orb_theme.position_rect_topleft; orb_state.py
```

```
owner: laris-engine-dev
arquivo: packages/laris/laris/platform/base.py, packages/laris/laris/platform/macos.py, packages/laris/laris/platform/windows.py
ação: alargar make_overlay para make_overlay(url, state=None) no Protocol e nas duas implementações (macOS ignora o argumento); em windows.py substituir _NoOpOverlay por um overlay que escreve no estado (show/hide) e que degrada para no-op silencioso quando state é None
critério_aceite: pytest local — make_overlay(url, state).show("dictate") deixa snapshot()["visible"] True e mode "dictate"; hide() volta para False/None; make_overlay(url) sem estado não levanta em nenhuma chamada; o teste atual que afirma o no-op é REESCRITO para o novo contrato, não deletado; macOS continua construindo seu overlay como hoje
depende_de: orb_state.py
```

```
owner: laris-engine-dev
arquivo: packages/laris/laris/daemon.py
ação: run(...) aceita orb_state=None, repassa-o a backend.make_overlay(overlay_url, state=orb_state) (:145) e marca orb_state.set_ready(True) imediatamente após backend.warm() (:140); nenhuma outra mudança de fluxo — os overlay.show()/hide() existentes (:92, :117, :186, :191, :212) já bastam
critério_aceite: pytest local do fluxo de ditado continua verde; com um estado injetado, ready vira True antes do print de "pronta"; run() sem orb_state se comporta exatamente como hoje
depende_de: orb_state.py; a mudança de make_overlay
```

```
owner: laris-engine-dev
arquivo: packages/laris/laris/__main__.py
ação: criar uma única instância de orb_state ao lado do voice_queue (:59) e passá-la tanto para build_app (:60) quanto para daemon.run (:98-105)
critério_aceite: subir `python -m laris` e, com o token de peers.json, GET /overlay/state responder ready=true depois que o modelo carrega, e visible alternar ao segurar a tecla de ditado
depende_de: server.py; daemon.py
```

## Critérios de aceite gerais (voxis-verify-windows / prova local)

Tudo abaixo é verificável **sem CI**, na máquina do usuário, no venv do laris:

- `pytest` do pacote laris verde, incluindo os casos novos de `position_rect_topleft`,
  `orb_state` e dos dois endpoints.
- Com `python -m laris` rodando: `GET /theme?token=…` sem params devolve exatamente o corpo
  de antes; com `screen_w=1920&screen_h=1080` devolve `rect` coerente com o seletor de
  posição do menu (trocar a posição e refazer a chamada muda o `rect`).
- `GET /overlay/state?token=…&since=0` responde na hora; com o `since` corrente e `wait=20`,
  segurar a tecla de ditado faz a chamada retornar em milissegundos com `visible=true`.
- Nenhum arquivo de `platform/macos.py` ou `overlay_app.py` aparece no diff.

## Riscos

- **Regressão silenciosa no macOS.** `daemon.py`, `server.py` e `platform/base.py` são
  compartilhados com o Mac, e ninguém está testando Mac neste fork. Toda mudança aqui é
  aditiva e com default `None` justamente por isso; qualquer parâmetro novo obrigatório
  quebraria o Mac sem que o CI percebesse.
- **`wait` segurando worker do uvicorn.** Mitigado pelo teto de 25s e pelo `asyncio.to_thread`.
  Só há um cliente esperado (o tray); N clientes seriam N threads.
- **Estado global contradizendo o desenho da factory.** O risco real é um dev futuro
  "simplificar" para um módulo-global. O docstring do `server.py` e o requisito 4 existem
  para impedir isso — repetir a justificativa no docstring do `orb_state.py`.
- **`ready` como falso conforto.** `set_ready(True)` diz que o `warm()` retornou, não que a
  primeira transcrição será rápida. É o melhor sinal disponível e é honesto o suficiente
  para o rótulo de menu.
- **Dívida registrada, fora de escopo:** `/ws/voice` tem consumidor único (dashboard e
  overlay se canibalizam) — pré-existente, não é regressão desta entrega. E `ASSISTANT_MODE`
  continua sendo setting morto: nada lê `config.MODE`, mas o tray persiste e valida o valor.
