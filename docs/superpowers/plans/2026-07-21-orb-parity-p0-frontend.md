# SDD-P0-FRONTEND — orb: reconexão do WebSocket, three.js sob demanda, cache de gradiente

owner: voxis-ui-dev
status: pronto para implementar
contrato: SDD-C0 (`2026-07-21-orb-parity-c0-contracts.md`) — só o §C1 importa aqui, e o orb
continua chamando `/theme` **sem** `screen_w`/`screen_h`.
depende_de: nenhum (independente de SDD-P0-ENGINE e de SDD-P1-TRAY)

## Contexto

Três defeitos do frontend do orb sobrevivem em qualquer plataforma, mas doem mais no Windows,
onde a janela fica aberta o tempo todo e o WebView2 é menos tolerante que o WebKit.

O `voice-orb.js` não reconecta: `ws.onclose = () => setPhase("idle")` (`:125`) e acabou. Como
salvar as configurações reinicia o daemon (`commands.rs:96-102`), **o orb congela até o
usuário desligar e religar o ditado** — e o usuário não tem como saber que foi isso.

O `three.min.js` (654 KB) é carregado sempre, por `<script>` estático em `overlay.html:54`,
mesmo com o tema default `waveform`, que é Canvas 2D puro. Uma varredura confirma que **só
`themes/faceted.js` referencia `THREE`** (13 ocorrências; `waveform.js` e `reactor.js`, zero).

E `themes/waveform.js` recria o `createRadialGradient` a cada frame (~linha 27): ~60
alocações por segundo cujo custo real é pressão de GC, ou seja, jank periódico — o tipo de
coisa que faz a UI "parecer" pior sem aparecer num profile de CPU médio.

## Objetivo / Não-objetivo

- Objetivo: o orb volta a animar sozinho depois de o engine reiniciar; o three.js só é
  baixado quando o tema `faceted` é escolhido; o gradiente do `waveform` para de ser
  realocado por frame.
- Não-objetivo: mudar o layout do `overlay.html` para o novo tamanho de janela. O
  `100vw/100vh` do `#orb-canvas-wrap` está **correto** — o defeito é a janela de 800×600 do
  lado Rust (SDD-P1-TRAY), não o CSS. Não "consertar" isso aqui. Também fora: qualquer coisa
  em `apps/tray/src/**` (é o SDD-P2), Python e Rust.

## Requisitos

1. O WebSocket `/ws/voice` reconecta sozinho com backoff exponencial de 500ms a 5s, resetado
   no `onopen`.
2. A reconexão só é agendada a partir do `onclose` do socket **corrente**, para não acumular
   sockets duplicados quando vários fecham em sequência.
3. Enquanto desconectado, a fase exibida é `idle` (comportamento atual preservado).
4. O modo `?demo=1` continua sem tocar em WebSocket algum.
5. `three.min.js` deixa de ser carregado no `<head>`/`<body>` do `overlay.html` e passa a ser
   buscado sob demanda, apenas quando o tema ativo é `faceted`.
6. Enquanto o three.js baixa, o orb pinta **imediatamente** com `waveform`, e faz a troca
   para `faceted` quando o script terminar de carregar.
7. Uma falha ao carregar o three.js não quebra o orb: `faceted.js:8` já degrada para
   `waveform` quando `THREE` é `undefined` — o contrato existe, falta só não baixar.
8. O three.js é carregado no máximo uma vez por página, mesmo com trocas repetidas de tema.
9. O gradiente do `waveform` é cacheado por `(energia quantizada, accent, dim)`, com a
   energia quantizada em ~16 degraus.
10. O desenho resultante do `waveform` é visualmente indistinguível do atual.

## Design

**Reconexão (0.4).** `connectVoice()` passa a ser reentrante e guarda o socket corrente numa
variável do closure. No `onclose`, só agenda a reconexão se `event.target === socketAtual`;
`onopen` zera o delay. Backoff `min(5000, delay * 2)` a partir de 500ms. Nada de
`setInterval`: um `setTimeout` por tentativa, para não empilhar.

**Lazy three.js (0.5).** Remover a `<script src="/static/vendor/three.min.js">` de
`overlay.html:54`. Em `voice-orb.js`, `mountTheme()` verifica se o tema pedido precisa do
three.js (lista explícita, hoje só `faceted`); se precisar e `window.THREE` for `undefined`,
monta `waveform` na hora e dispara um carregador que injeta a tag `<script>` uma única vez
(promessa memoizada), remontando o tema ao resolver. `onerror` do script resolve como falha
e deixa o `waveform` no lugar.

Importante: a lista de temas que precisam de three.js fica no `voice-orb.js`, não em cada
tema, porque a decisão precisa ser tomada **antes** de o módulo do tema rodar.

**Cache de gradiente (0.6).** Chave `${quantV}|${accent}|${dim}` com
`quantV = Math.round(v * 15)`; um objeto `Map` no closure do tema, limpo no `dispose()` e
quando o tamanho do canvas muda (o gradiente depende do raio). Ganho modesto no frame, mas
reduz a pressão de GC.

**Alternativas descartadas.**
- *Bundler / ES modules dinâmicos (`import()`)* para o three: o overlay é servido como
  arquivos estáticos por `StaticFiles` do FastAPI e não há passo de build no pacote Python.
  Injetar `<script>` é a rota de menor superfície. Rejeitada.
- *Reconectar recarregando a página (`location.reload()`)* no `onclose`: refaz o download de
  tudo e pisca a janela transparente. Rejeitada.
- *Cachear o gradiente por valor exato de `v`*: o `v` é contínuo, o cache nunca acertaria.
  Daí a quantização. Rejeitada.

## Tarefas por owner

```
owner: voxis-ui-dev
arquivo: packages/laris/frontend/voice-orb.js
ação: tornar connectVoice() reconectante — backoff exponencial 500ms->5s resetado no onopen, agendamento apenas a partir do onclose do socket corrente (comparar com a referência guardada), um setTimeout por tentativa, e o caminho ?demo=1 intocado
critério_aceite: com o overlay aberto no navegador, matar o `python -m laris` e religar; o orb volta a animar SEM F5, em <5s; no DevTools, a aba Network/WS mostra uma única conexão viva por vez (nenhum socket duplicado acumulado após vários ciclos)
depende_de: nenhum
```

```
owner: voxis-ui-dev
arquivo: packages/laris/frontend/overlay.html, packages/laris/frontend/voice-orb.js
ação: remover a tag <script src="/static/vendor/three.min.js"> de overlay.html:54; em mountTheme(), carregar o three.js sob demanda (injeção de <script>, promessa memoizada, uma vez por página) apenas para os temas que precisam dele (hoje só `faceted`), pintando waveform imediatamente enquanto baixa e remontando ao resolver; onerror mantém waveform
critério_aceite: DevTools > Network com o tema `waveform` — three.min.js NÃO aparece; ao trocar para `faceted` no menu do tray, aparece uma vez e o orb passa a renderizar faceted; trocar de tema ida e volta não baixa de novo; bloquear a URL do three no DevTools e escolher faceted mantém o orb desenhando waveform sem erro fatal no console
depende_de: nenhum
```

```
owner: voxis-ui-dev
arquivo: packages/laris/frontend/themes/waveform.js
ação: cachear o createRadialGradient por chave (energia quantizada em ~16 degraus, accent, dim) num Map do closure, invalidado no dispose() e em mudança de tamanho do canvas
critério_aceite: profile de ~30s no DevTools com ?demo=1 mostra queda clara nas alocações por frame do gradiente; comparação visual lado a lado (antes/depois, mesma paleta) sem diferença perceptível
depende_de: nenhum
```

## Critérios de aceite gerais (prova local, sem CI)

Roteiro único, todo no navegador — nenhum Rust envolvido:

1. `python -m laris`, abrir `http://127.0.0.1:<porta>/overlay?token=<de peers.json>&demo=1`.
   O `?demo=1` já simula o ciclo idle/speaking.
2. Redimensionar a janela do navegador para ~190×190 reproduz o rect final da Fase 1 — o orb
   deve ficar proporcional e legível nesse tamanho.
3. Network: `three.min.js` ausente no tema `waveform`, presente ao trocar para `faceted`.
4. Sem `demo=1`, matar o engine com o overlay aberto e religar: o orb volta a animar sem F5.
   Este é o teste direto do bug de "salvar settings congela o orb".
5. Console sem erros novos.

## Riscos

- **O macOS usa exatamente estes mesmos arquivos.** `overlay.html`, `voice-orb.js` e os temas
  são servidos pelo mesmo FastAPI no Mac, dentro do `NSPanel` do `overlay_app.py`, e ninguém
  está testando Mac neste fork. Toda mudança de render aqui afeta o Mac sem rede de proteção.
  Mitigação possível: manter as mudanças puramente aditivas/comportamentais e evitar mexer no
  CSS de `voice-orb.css` e no layout do `overlay.html` além da remoção da tag do three.
- **Reconexão contra um engine morto para sempre.** O backoff tem teto de 5s; uma máquina com
  o daemon desligado à noite faz uma tentativa a cada 5s indefinidamente. Custo desprezível
  em loopback, mas se a janela do orb passar a ficar escondida (SDD-P1-TRAY), o navegador
  congela o timer — o que na prática resolve sozinho.
- **`#orb-fallback`** está posicionado em `top: 16px; left: 16px` com 80px, um layout pensado
  para a janela grande. Numa janela de 190×190 ele fica descentralizado durante o instante
  antes do primeiro `mountTheme()`. Com o three.js fora do caminho crítico, esse instante
  passa a ser quase zero; se ainda incomodar, centralizar é ajuste trivial — não é bloqueante.
- **Dívida registrada:** `/ws/voice` entrega eventos a um consumidor único; abrir o dashboard
  junto com o overlay faz os dois roubarem eventos um do outro. Pré-existente, não é
  regressão desta entrega, e a reconexão automática pode torná-lo *mais* visível (dois
  clientes agora insistem em reconectar).
