# SDD-P1-TRAY — janela do orb: tamanho, posição, ciclo de vida e custo do poll

owner: tray-dev
status: pronto para implementar
contrato: **SDD-C0** (`2026-07-21-orb-parity-c0-contracts.md`). Todo payload, unidade e
semântica de `serial`/`wait` vem de lá — não reinterpretar.
depende_de: SDD-P0-ENGINE (os dois endpoints precisam existir para o smoke; o código Rust
pode ser escrito antes, contra o contrato)

## Contexto

`overlay.rs:26-34` cria a janela do orb **sem `.inner_size()` e sem `.position()`**. Ela cai
no default 800×600 do Tauri, na posição de cascata do Windows. Como `overlay.html` força
`100vw/100vh` no `#orb-canvas-wrap`, o orb é esticado para ~800×800 em vez dos 190×190 do
tema: ~17× mais pixels por frame, e como os traços escalam por `S = size/280`, ficam ~4× mais
grossos. Não é o mesmo desenho aumentado — é outro desenho.

Pior, `lib.rs:359-365` prende o ciclo de vida da janela a `laris_alive`, não à fase de ditado.
Uma janela transparente always-on-top anima 24h por dia para um recurso usado ~1% do tempo.

E o seletor de posição do menu **não está quebrado — nunca teve consumidor no Windows**:
`orb_theme.position_rect()` só é lido por `overlay_app.py`, que é macOS-only.

Este SDD é a única parte do trabalho que **não é verificável nesta máquina**: não há cargo
local, e o `cargo test` do CI (`tray-build.yml`, job `windows-latest`) é o primeiro compilador
a ver este código. Por isso a aritmética foi deliberadamente empurrada para o Python
(SDD-P0-ENGINE) e o que sobra aqui é wiring.

## Objetivo / Não-objetivo

- Objetivo: a janela do orb passa a ter o tamanho e a posição do tema, aparece só durante o
  ditado, acompanha ao vivo mudanças do seletor de posição/tamanho, e o custo contínuo do
  poll do tray cai.
- Não-objetivo: Python, CSS de `apps/tray/src/**`, e drag do orb (plano B explicitamente
  descartado — o seletor de posição resolve). Sem novas dependências no `Cargo.toml`.

## Requisitos

1. A janela do orb é criada com `.inner_size()` e `.position()` derivados do `rect` de
   `/theme`, e com `.visible(false)`.
2. A janela é **persistente**: alterna visibilidade em vez de ser criada e destruída a cada
   ditado.
3. Tamanho e posição são reaplicados **apenas quando o rect muda**, comparando com o último
   valor guardado no state.
4. O rect é sempre aplicado **antes** do `show()`, nunca com a janela visível.
5. Rect e tamanho são tratados em **unidades lógicas** (`LogicalPosition`/`LogicalSize`), e
   `screen_w`/`screen_h` enviados ao `/theme` são a área útil em px lógicos
   (`físico / scale_factor`).
6. O monitor de referência é o que contém o cursor (`cursor_position()`), com fallback
   `primary_monitor()`; a origem desse monitor é somada ao `rect`, que vem relativo ao
   monitor (SDD-C0 §7).
7. Usa `Monitor::work_area()` quando disponível na versão fixada do Tauri; senão `size()`,
   com a limitação documentada no código.
8. A visibilidade segue `visible` de `GET /overlay/state`, consumido por long-poll numa
   thread dedicada, com backoff de 1s a 5s em erro e `visible=false` assumido em falha
   (SDD-C0 §24-25).
9. O poll de 2s existente continua responsável por criar/destruir/redimensionar; `rect` entra
   no `Snapshot` e portanto participa do `PartialEq` que decide o rebuild — **é assim que o
   seletor de posição passa a funcionar ao vivo**, reaproveitando a infra existente.
10. O orb não é criado enquanto `ready` for `false`, e o item de menu do ditado mostra
    `Ditado (carregando modelo…)` enquanto `laris_alive && !ready`.
11. O `GET /theme` do tick só é refeito quando o mtime de `orb-theme.json` muda, com uma
    busca de segurança a cada ~30 tiques.
12. `alive()` TCP passa a rodar 1 tick em 5.
13. `get_settings` usa timeouts curtos: ~700ms no `/theme` de UI e ~150ms no `alive()`.
14. `icon_as_template(true)` (`lib.rs:326`) fica sob `#[cfg(target_os = "macos")]`.
15. O ícone da bandeja é escolhido por `scale_factor()` entre variantes desenhadas em 16/20/
    24/32, em PNG.
16. A janela de settings ganha `.center()`, `.min_inner_size(480, 520)` e `.theme(None)`.
17. Um `initialization_script` sob `#[cfg(windows)]` marca a plataforma na página de settings
    antes de qualquer script dela rodar.
18. Os testes Rust existentes continuam verdes; a aritmética nova ganha teste puro, isolado de
    `AppHandle`.

## Design

**`sync()` no lugar de `open()` (1.1).** `overlay.rs:18-20` retorna cedo quando a janela já
existe, o que torna impossível redimensionar. A função vira reconciliação, recebendo rect e
visibilidade:

- **Não existe** → builder com as flags atuais (`transparent`, `decorations(false)`,
  `always_on_top`, `skip_taskbar`, `focused(false)`, `resizable(false)`, `shadow(false)`)
  **mais `.inner_size(w,h)`, `.position(x,y)` e `.visible(false)`**, seguido de
  `set_ignore_cursor_events(true)`.
- **Existe** → `set_size`/`set_position` **só se o rect mudou**. Reposicionar uma janela
  transparente a cada 2s força repaint à toa.
- **Visibilidade** → `show()` / `hide()`.

Manter uma janela persistente e alternar visibilidade, em vez de criar e destruir a cada
ditado: recriar recarregaria o bundle do orb e refaria o handshake do WebSocket toda vez. Uma
janela oculta no Chromium não compõe no DWM e tem o `requestAnimationFrame` congelado —
exatamente o efeito de economia desejado.

**Unidades, multi-monitor e taskbar (1.2).** `NSScreen.frame` é em pontos lógicos, e é essa a
unidade que `orb_theme` assume; por isso o Rust envia tamanho lógico e aplica
`LogicalPosition`/`LogicalSize`. Assim `size: 190` significa 190px lógicos nas duas
plataformas, e um monitor a 150% mostra o orb do mesmo tamanho aparente do Mac.

`position_rect` trabalha em coordenadas relativas ao monitor, então a origem do monitor
escolhido é somada depois. A escolha por `cursor_position()` é o equivalente prático do
`mainScreen()` do AppKit.

Sobre `work_area()`: a versão fixada é **tauri 2.11.5** (`Cargo.lock:3453-3454`).
`Monitor::work_area()` deve ser **confirmado nessa versão exata antes de escrever a chamada**
— sem compilador local, um método inexistente custa um ciclo inteiro de CI. Se não existir,
usar `size()` e comentar no código que `bottom-*` pode ficar sob a taskbar. No macOS o
`_TOP_MARGIN = 40` do `orb_theme` compensa a menu bar; no Windows, sem work area, a margem
inferior não compensa nada.

**Wiring em `lib.rs` (1.3).** As duas responsabilidades ficam separadas:

- O poll de 2s já faz `GET /theme` (`lib.rs:64-74`). Passa a mandar `screen_w`/`screen_h` e a
  ler `rect`, guardando-o no `Snapshot` junto com `ready`. O `PartialEq` do `Snapshot` já é o
  gatilho de rebuild — nenhuma máquina de estado nova.
- Uma **thread nova** roda o long-poll de `/overlay/state` e chama `run_on_main_thread` para
  alternar a visibilidade.

**Cuidado com o agente HTTP.** `laris::agent()` (`laris.rs:39-45`) tem
`timeout_global(Some(2s))`. Um long-poll de 20s morreria nele. O long-poll precisa do **seu
próprio agente**, com timeout global maior que o `wait` enviado (ex.: `wait=20`, timeout 30s),
mantendo `.proxy(None)` — `HTTP_PROXY` rotearia a chamada com token para fora da máquina.

**Custo contínuo (Fase 3).** O caro do tick é o `GET /theme`. O tema vive num arquivo:
`stat()` do mtime de `orb-theme.json` e busca só quando mudar, com uma busca de segurança a
cada ~30 tiques. É o mesmo padrão que `overlay_app.py:101` já usa no macOS. O `alive()` TCP
cai para 1 tick em 5, porque a conexão viva do long-poll já é um sinal de vida melhor.

**Indicador de carregamento.** O uvicorn sobe antes do `backend.warm()`, então `laris_alive`
mente: hoje o tray abre o orb e a tecla não responde. Com `ready` (SDD-C0 §16) o menu passa a
dizer `Ditado (carregando modelo…)` e o orb não é criado antes da hora. Ficou muito mais
visível desde que o modelo passou a ser Whisper `large` em CPU int8.

**Ícone (Fase 4).** `icon_as_template(true)` é conceito do AppKit e **no-op no Windows**. Os
PNGs são 44×44 (22pt@2x, medida de macOS); a bandeja do Windows pede 16/20/24/32 conforme DPI,
e o downscale de 0,36× é o que deixa borrado. Manter PNG: `Image::from_bytes` não lê `.ico`
multi-resolução (o `.ico` serve ao `bundle.icon`, onde já está correto). Para o ícone ciano
cru não sumir numa taskbar clara, desenhar com contorno/halo. Adaptação real ao tema do
sistema (lendo `SystemUsesLightTheme` do registro) fica para depois.

**Classe de plataforma sem flash (apoio ao SDD-P2).** `main.ts` já tem `isWindows` (via
`std::env::consts::OS` no `get_settings`), mas `load()` é async: uma classe aplicada ali chega
depois do primeiro paint. Um `initialization_script` no builder da janela de settings, sob
`#[cfg(windows)]`, roda antes de qualquer script da página. O `isWindows` do `main.ts`
permanece só para lógica (tecla default, modelo STT) — não duplicar propósito.

**Alternativas descartadas.**
- *Tray assinando `/ws/voice`* — rejeitada; ver SDD-C0 §Design (rouba eventos do orb, e exige
  um crate novo que não compila localmente).
- *Criar e destruir a janela a cada ditado* — recarrega bundle e refaz handshake do WS.
- *Fazer a conversão bottom-left→top-left em Rust* — sem cargo local, cada erro de margem
  custa um ciclo de CI. Fica em Python, onde há pytest. Rejeitada.
- *Drag do orb com o mouse* — plano B do plano original; desnecessário com o seletor
  funcionando, e conflitaria com `set_ignore_cursor_events(true)`. Rejeitada.
- *`.ico` multi-resolução para a bandeja* — `Image::from_bytes` não lê. Rejeitada.

## Tarefas por owner

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/overlay.rs
ação: substituir open() por uma função de reconciliação sync(app, url, rect, visible) — cria a janela (flags atuais + inner_size + position + visible(false) + set_ignore_cursor_events) quando não existe; quando existe, aplica set_size/set_position SÓ se o rect mudou, e depois show()/hide(); rect sempre aplicado antes do show(), nunca com a janela visível; usar LogicalSize/LogicalPosition; manter close() e o caminho #[cfg(not(windows))] como no-op
critério_aceite: cargo test verde no CI; teste puro novo da aritmética de rect (soma da origem do monitor + conversão físico->lógico) isolado de AppHandle; o teste overlay_url_carries_token permanece intacto
depende_de: nenhum (escrito contra SDD-C0)
```

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/laris.rs
ação: (a) get_theme passa a aceitar screen_w/screen_h opcionais e a devolver também o rect; (b) nova função de long-poll de GET /overlay/state?since=&wait=20 com um agente próprio (timeout global ~30s, .proxy(None)) — NÃO reusar o agent() de 2s, que mataria o long-poll; comparar serial por desigualdade, nunca por >
critério_aceite: cargo test verde; teste de parsing dos dois payloads a partir de JSON literal copiado do SDD-C0 (rect presente/ausente; overlay/state com serial menor que o anterior é tratado como mudança, não ignorado)
depende_de: SDD-P0-ENGINE (endpoints reais para o smoke)
```

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/lib.rs
ação: (a) Snapshot ganha rect e ready; take_snapshot escolhe o monitor por cursor_position() com fallback primary_monitor(), envia work_area (ou size(), ver risco) em px lógicos ao /theme e guarda o rect somado à origem do monitor; (b) o tick chama overlay::sync em vez de open/close, e não cria a janela enquanto !ready; (c) thread nova para o long-poll de /overlay/state alternando visibilidade via run_on_main_thread, com backoff 1s->5s e visible=false em erro; (d) build_menu mostra "Ditado (carregando modelo...)" quando laris_alive && !ready
critério_aceite: cargo test verde; no MSI, o roteiro manual completo da seção de critérios de aceite gerais passa
depende_de: overlay.rs sync(); laris.rs long-poll; SDD-P0-ENGINE
```

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/lib.rs
ação: baratear o tick — só refazer GET /theme quando o mtime de orb-theme.json mudar (com refetch de segurança a cada ~30 tiques, mesmo padrão de overlay_app.py:101) e rodar alive() 1 tick em 5, reaproveitando o último valor conhecido nos demais
critério_aceite: cargo test verde; com o daemon parado, o menu ainda reflete "ditado desligado" em <=10s; trocar a posição do orb no menu reflete no orb em <=2 tiques
depende_de: a mudança de Snapshot acima
```

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/commands.rs
ação: (a) get_settings usa timeouts curtos (~700ms no /theme, ~150ms no alive()) em vez do agente global de 2s; (b) show_settings_window ganha .center(), .min_inner_size(480, 520), .theme(None) e, sob #[cfg(windows)], um initialization_script que marca a plataforma no <html> antes do primeiro paint (a classe consumida pelo SDD-P2)
critério_aceite: a janela de settings abre centralizada e pinta em <100ms com o estado de loading do SDD-P2; nenhuma janela menor que 480x520 é alcançável por resize; a classe de plataforma já está no <html> no primeiro paint (verificável no DevTools do WebView2)
depende_de: nenhum; coordenar o NOME exato da classe com o SDD-P2 antes de escrever
```

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/lib.rs, apps/tray/src-tauri/icons/
ação: envolver icon_as_template(true) (:326) em #[cfg(target_os = "macos")]; gerar variantes PNG de tray-idle/tray-rec desenhadas em 16/20/24/32 (não downscale do 44x44) com contorno/halo para sobreviver a taskbar clara, e escolher a variante por scale_factor()
critério_aceite: no Windows, o ícone da bandeja fica nítido a 100%, 125% e 150%; visível tanto no tema claro quanto no escuro; macOS continua com o ícone template
depende_de: nenhum
```

## Critérios de aceite gerais (voxis-verify-windows, passada manual no MSI)

Nada aqui é provável localmente — o CI compila, e a passada manual valida. Roteiro:

1. Ligar o ditado → **nenhum orb visível**; enquanto o modelo carrega, o menu mostra
   `Ditado (carregando modelo…)`.
2. Segurar a tecla de ditado → orb **pequeno** (tamanho do tema) e **no lugar do seletor**.
3. Soltar → o orb some.
4. Mudar a posição no menu → segurar de novo → orb aparece no lugar novo.
5. Mudar o tamanho → idem.
6. Salvar as configurações (que reinicia o daemon) → segurar a tecla → o orb ainda anima.
7. Segundo monitor com DPI diferente → o orb tem o mesmo tamanho aparente.
8. Com o ditado ocioso, o processo do WebView2 do orb não aparece consumindo CPU contínua.

No CI: `cargo test` verde em `windows-latest`, com o teste puro de `overlay_url` preservado e
o teste novo da aritmética de rect.

## Riscos

- **`Monitor::work_area()` pode não existir em tauri 2.11.5.** Confirmar antes de escrever a
  chamada; sem cargo local, descobrir isso custa um ciclo de CI. Fallback `size()` com a
  limitação documentada.
- **Nada disto compila nesta máquina.** Todo o código novo é `#[cfg(windows)]` ou toca o
  caminho Windows; macOS/Linux verdes no CI não provam nada sobre ele. Mesma armadilha
  registrada no SDD-Tray-Windows de 2026-07-20.
- **Janela transparente piscando ao reposicionar.** Mitigado pela regra de aplicar o rect
  sempre antes do `show()`.
- **Timeout global do agente matando o long-poll.** É o erro mais provável de introduzir:
  reusar `agent()` faz o long-poll falhar a cada 2s e vira um poll caro disfarçado. O
  critério de aceite (a chamada retorna em ~20s, não em ~2s) precisa ser observado no smoke.
- **`serial` reiniciando quando o daemon reinicia** (salvar settings faz isso). Comparar por
  desigualdade — SDD-C0 §23.
- **Cache por mtime mascarando mudança de tema.** Se o `orb-theme.json` for escrito com mtime
  de granularidade grosseira, duas gravações no mesmo segundo podem passar despercebidas. O
  refetch de segurança a cada ~30 tiques existe justamente para limitar o estrago a ~1min.
- **Reuso da janela entre monitores.** Mover o cursor para outro monitor entre dois ditados
  troca o monitor de referência; o rect muda e a janela é reposicionada. Esperado, mas é a
  fonte mais provável de "o orb apareceu no monitor errado" em relato futuro.
