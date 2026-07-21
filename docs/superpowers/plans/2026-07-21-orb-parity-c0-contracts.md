# SDD-C0 — Contratos HTTP do orb (normativo, cross-owner)

owner: nenhum (documento normativo; implementado por SDD-P0-ENGINE, consumido por SDD-P1-TRAY)
status: congelado — mudar aqui antes de mudar qualquer lado
consumidores: `packages/laris/laris/server.py` (produtor), `apps/tray/src-tauri/src/laris.rs` +
`overlay.rs` + `lib.rs` (consumidor), `packages/laris/frontend/voice-orb.js` (consumidor parcial de `/theme`)

## Contexto

O trabalho de paridade de UI do orb no Windows cria duas interfaces novas entre o
engine Python e o tray Rust: o retângulo de posicionamento da janela do orb e o
estado de visibilidade/prontidão. Python define, Rust consome, e não há compilador
Rust nesta máquina — uma divergência de contrato só apareceria depois de um ciclo
completo de CI. Por isso os dois contratos moram aqui, em um único documento, e os
SDDs de implementação **referenciam** este arquivo em vez de redescrever payloads.

Regra: nenhum campo, nome de query param, unidade ou semântica de bloqueio pode ser
alterado em um lado sem editar este documento primeiro.

## Objetivo / Não-objetivo

- Objetivo: especificar, sem ambiguidade, `GET /theme` (extensão) e `GET /overlay/state`
  (novo) — payload exato, tipos, unidades, origem de coordenadas, semântica de
  `serial`/`wait`, autenticação, e comportamento do cliente em erro.
- Não-objetivo: descrever *como* Python guarda o estado (SDD-P0-ENGINE) ou *como* o
  Rust aplica o rect na janela (SDD-P1-TRAY). Nenhum código de produto sai daqui.

## C1 — `GET /theme` (extensão retrocompatível)

### Requisição

```
GET /theme?token=<str>&screen_w=<float>&screen_h=<float>
```

1. `token` — inalterado, obrigatório, `403` se inválido.
2. `screen_w` e `screen_h` são **opcionais** e formam um par: só têm efeito quando
   **ambos** presentes e **ambos > 0**. Qualquer outro caso (nenhum, só um, zero,
   negativo) é tratado como "não pedido".
3. Valores não numéricos seguem o comportamento padrão do FastAPI (`422`). O tray
   nunca envia valores não numéricos; isso é contrato para o navegador/curl.

### Resposta

Sem os params — **byte-a-byte a resposta de hoje**, sem a chave `rect`:

```json
{ "theme": { ... }, "palettes": { ... } }
```

Com o par válido, a mesma resposta **mais** uma chave de topo `rect`:

```json
{ "theme": { ... }, "palettes": { ... },
  "rect": { "x": 865.0, "y": 445.0, "w": 190.0, "h": 190.0 } }
```

4. `rect.w == rect.h == float(theme["size"])`.
5. **Origem top-left**, eixo Y crescendo para baixo (convenção Win32/Tauri).
6. **Unidades: pixels lógicos** (DIP). Não físicos. O cliente que enviou
   `screen_w`/`screen_h` em pixels lógicos recebe `rect` em pixels lógicos.
7. **Relativo ao monitor**, não ao desktop virtual: `x`/`y` estão em `[0, screen_w]` /
   `[0, screen_h]`, e somar a origem do monitor é responsabilidade do cliente.
8. `screen_w`/`screen_h` devem ser a **work area** do monitor (área útil, descontada a
   taskbar) quando o cliente conseguir obtê-la — ver SDD-P1-TRAY para o fallback.
9. Os quatro valores são `float` no JSON. Podem ser negativos ou exceder a tela quando
   `position == "custom"` ou `size` maior que a tela; o servidor **não** faz clamp — o
   cliente decide (o macOS também não faz).
10. `position == "custom"`: `theme["custom"]` é `[x, y]` na convenção **bottom-left**
    herdada do AppKit e permanece assim no disco. O `rect` converte como qualquer
    outra posição: `y = screen_h - custom[1] - size`.

### Retrocompatibilidade

11. O macOS (`overlay_app.py`) e o `main.ts` do tray continuam chamando `/theme` sem os
    params e **não podem** observar diferença alguma. Um teste dedicado afirma a
    ausência da chave `rect` nesse caso.

## C2 — `GET /overlay/state` (novo)

### Requisição

```
GET /overlay/state?token=<str>&since=<int>&wait=<float>
```

12. `token` — mesmo esquema de `/theme`; `403` se inválido.
13. `since` — inteiro, default `0`. É o último `serial` que o cliente viu.
14. `wait` — segundos, float, default `0`. Clamp do servidor para `[0.0, 25.0]`;
    valores acima são silenciosamente reduzidos a 25.

### Resposta (sempre `200`, sempre este shape)

```json
{ "visible": false, "ready": true, "mode": null, "serial": 7 }
```

15. `visible` (bool) — o orb deve estar na tela agora. Espelha `overlay.show()` /
    `overlay.hide()` chamados pelo `daemon.py`.
16. `ready` (bool) — `backend.warm()` concluiu; o modelo STT está carregado e a tecla
    responde. Antes disso o daemon já responde HTTP e `alive()` já é `true`.
17. `mode` (string | null) — o argumento do último `show(mode)`: hoje `"dictate"` ou
    `"transcribing"`. `null` quando `visible` é `false`. Informativo; o tray não é
    obrigado a agir sobre ele nesta entrega.
18. `serial` (int) — começa em **1** e é **estritamente crescente** dentro de um
    processo. Incrementa a cada mudança observável da tupla `(visible, ready, mode)`.
    Nunca vale `0`, portanto `since=0` **sempre** retorna imediatamente — é assim que o
    cliente faz a primeira leitura.

### Semântica de bloqueio

19. Se `serial != since`, responde **imediatamente** com o estado corrente.
20. Se `serial == since` e `wait > 0`, o servidor bloqueia até `serial` mudar ou até
    `wait` expirar. O bloqueio nunca ocorre no event loop do asyncio (ver SDD-P0-ENGINE).
21. Ao expirar sem mudança, responde `200` com o estado corrente e o **mesmo** `serial`.
    Não há `304`, não há corpo vazio.
22. A latência de acordar um cliente após uma mudança deve ser da ordem de milissegundos
    (evento, não polling interno).

### Regras do cliente (normativas para o tray)

23. O cliente compara por **desigualdade**, nunca por `>`. Um reinício do daemon (que
    salvar settings provoca) zera o `serial` para 1, e um cliente que exigisse
    monotonicidade global travaria para sempre.
24. Erro de conexão, `403`, ou corpo malformado: o cliente assume `visible = false`,
    esconde o orb, e refaz com backoff exponencial de 1s a 5s. Nunca panica a thread.
25. `wait` recomendado para o tray: 20s (abaixo do teto de 25s, com folga para o timeout
    global de HTTP do cliente, que deve ser **maior** que `wait` — um timeout global de
    2s como o de `/theme` hoje mataria todo long-poll).

## Design (por que assim)

O tray precisa saber quando mostrar o orb. Três desenhos foram considerados:

- **Tray assina `/ws/voice`** — rejeitado. A fila é `thread_queue.Queue()` de consumidor
  único (`server.py:40`, `get`/`to_thread` no `ws_voice`); um segundo assinante **rouba
  eventos do orb**. Exigiria também um crate de WebSocket novo no Rust, que o usuário não
  consegue compilar localmente.
- **O JS do orb pede hide pela API do Tauri** — inviável: o HTML vem do FastAPI e o
  builder está com `withGlobalTauri: false`; a página não tem `__TAURI__`.
- **Python publica estado, tray consulta com long-poll** — escolhido. Zero dependências
  novas dos dois lados (`ureq` já está no `Cargo.toml`), latência ~0, e restaura a
  semântica do macOS sem tocar em `daemon.py`, que já chama `overlay.show()` (`:186`) e
  `overlay.hide()` (`:212`).

A conversão de coordenadas bottom-left → top-left mora em Python de propósito: é onde há
teste rodando localmente nesta máquina. Em Rust, um erro de margem só apareceria depois de
um ciclo completo de CI.

## Critérios de aceite (verificáveis localmente, sem CI)

- `GET /theme?token=X` (sem par) → resposta idêntica à de hoje, **sem** a chave `rect`.
- `GET /theme?token=X&screen_w=1920&screen_h=1080` com o tema default
  (`position=center`, `size=190`) → `rect == {"x": 865.0, "y": 445.0, "w": 190.0, "h": 190.0}`.
- `position=top-left` no mesmo tamanho de tela → `rect.x == 16.0` e `rect.y == 40.0`.
- Para toda posição não-`custom`: `y_topleft + y_bottomleft + size == screen_h`.
- `GET /overlay/state?token=X&since=0` → responde em <50ms com `serial >= 1`.
- `GET /overlay/state?token=X&since=<serial atual>&wait=1` → retorna em ~1s com o mesmo
  `serial`.
- Mesma chamada com `wait=20`, e uma outra thread chamando `show("dictate")` após 200ms →
  retorna em ~200ms com `visible=true`, `mode="dictate"` e `serial` incrementado.
- `wait=999` não bloqueia mais que ~25s.

## Riscos

- **Divergência silenciosa de unidades.** Se o Rust mandar `screen_w` físico e aplicar o
  rect como lógico, o orb fica no lugar errado só em monitores com DPI != 100% — e o dev
  provavelmente testa em 100%. Mitigação: o teste manual do MSI inclui explicitamente um
  segundo monitor com escala diferente.
- **`serial` reiniciando.** Coberto pelo item 23, mas é a pegadinha mais fácil de
  introduzir num refactor futuro do lado Rust.
- **Long-poll segurando worker do uvicorn.** Mitigado pelo teto de 25s e pelo
  `asyncio.to_thread`; ainda assim, N clientes = N threads. Só há um cliente (o tray).
- **Dívida pré-existente: `/ws/voice` tem consumidor único.** Abrir o dashboard e o
  overlay ao mesmo tempo faz os dois canibalizarem eventos. **Não é regressão deste
  trabalho** e nada aqui piora a situação (o tray deliberadamente não assina o WS), mas
  fica registrado: o fan-out do `/ws/voice` é trabalho futuro.
