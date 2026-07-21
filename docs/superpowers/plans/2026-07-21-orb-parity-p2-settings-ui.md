# SDD-P2-SETTINGS-UI — CSS replicando o macOS na janela de configurações

owner: voxis-ui-dev
status: pronto para implementar
depende_de: nenhum para começar; os flags da janela e o `initialization_script` são tarefa do
SDD-P1-TRAY (`2026-07-21-orb-parity-p1-tray.md`) — **os nomes de classe abaixo são o contrato
entre os dois documentos**.

## Contexto

O usuário relatou que o visual do Windows é "muito pior" que o do macOS. Não há nada
Apple-only quebrado: `apps/tray/src/styles.css` tem **19 linhas** e não estiliza `button`,
`select`, `input` nem `checkbox`. O app nunca estilizou nada — confiou no widget nativo. O
default do macOS (Aqua, via WebKit) é bonito de graça; o do WebView2/Chromium é chapado. A
diferença está no que *não* foi escrito.

Somam-se três detalhes: um font stack Apple-first a 13px (tamanho calibrado para SF Pro, não
para Segoe UI, que lê menor e mais leve no mesmo corpo), `color-mix()` como único separador
visual (`styles.css:9`), e a janela abrindo em branco porque `get_settings` bloqueia até ~2,3s
(`alive()` 300ms + `get_theme()` com timeout de 2s) enquanto `main.ts:185` é `load().then(bind)`.

Direção de produto já decidida: **replicar o look do macOS**, com CSS próprio imitando Aqua,
o mesmo CSS nas duas plataformas. Explicitamente **não** usar Mica/Acrylic/Fluent.

## Objetivo / Não-objetivo

- Objetivo: a janela de configurações no Windows fica visualmente equivalente à do macOS —
  controles desenhados, hairlines, focus ring Aqua, tipografia compensada — e pinta algo útil
  em menos de 100ms.
- Não-objetivo: mudar a estrutura de seções ou o comportamento de qualquer setting; mexer em
  Rust (é o SDD-P1-TRAY) ou no frontend do orb (é o SDD-P0-FRONTEND); relaxar a CSP; adotar
  qualquer design system do Windows.

## Requisitos

1. `apps/tray/src/styles.css` é reescrito em torno de custom properties, com os valores
   derivados **declarados explicitamente** em claro e em `@media (prefers-color-scheme: dark)`.
2. **Nenhum uso de `color-mix()`** — hoje é o único separador visual e some silenciosamente em
   WebView2 antigo, sem fallback.
3. Todos os controles usam `appearance: none` e são redesenhados: `button`, `select`,
   `input[type=text]`, `input[type=number]`, `input[type=checkbox]`, `textarea`.
4. Bordas **hairline de 0.5px** e sombras minúsculas — é o detalhe que mais "faz" o Aqua;
   controles macOS não têm borda sólida de 1px.
5. Focus ring Aqua: halo difuso de ~3px via `box-shadow`, não `outline`. É a assinatura visual.
6. O chevron do `<select>` e o check do checkbox são desenhados com **pseudo-elementos**,
   nunca com `data:` URI. A CSP é
   `default-src 'self'; connect-src ipc: http://ipc.localhost; style-src 'self' 'unsafe-inline'`
   — **não há `img-src`**, então herda `'self'` e um SVG em `data:` é bloqueado. Não relaxar a
   CSP para contornar.
7. Cada `<select>` do `index.html` é envolvido num wrapper, para o pseudo-elemento do chevron
   ter onde ancorar (um `<select>` não pode ter `::after`).
8. `::-webkit-scrollbar` estilizada com thumb arredondado sobre track transparente (borda
   transparente + `background-clip: padding-box`), mais `scrollbar-gutter: stable`.
9. Tipografia com paridade de renderização aproximada com SF Text.
10. Estado de loading: a janela mostra estrutura, não branco, desde o primeiro paint.
11. A classe de plataforma injetada pelo Rust é consumida pelo CSS para os ajustes
    Windows-only, e o `isWindows` do `main.ts` continua servindo só para lógica.

## Design

**Tokens.** `--bg`, `--fg`, `--fg-secondary`, `--separator`, `--control-bg`,
`--control-border`, `--accent` (`#007aff` claro / `#0a84ff` escuro), `--accent-ring`,
`--radius-control: 6px`, e as sombras. Declarados duas vezes, literais, sem função de cor.

**Controles.** Botão de 22px de altura, gradiente vertical sutil, `:active` com o gradiente
invertido; botão default com fundo `--accent` e texto branco; inputs com sombra interna
(`inset`); checkbox 14x14 com raio 3.5px e o check desenhado como duas bordas rotacionadas.

**Chevron sem SVG.** O wrapper recebe `position: relative` e um `::after` com duas bordas
(`border-right` + `border-bottom`) e `transform: rotate(45deg)`, posicionado à direita, com
`pointer-events: none` para não roubar o clique do `<select>`.

**Fonte.** SF Pro não existe no Windows e não é redistribuível. Duas rotas:

- *Recomendada:* empacotar **Inter var** (SIL OFL, ~110 KB woff2) como asset local em
  `apps/tray/src/`. A CSP não tem `font-src`, então herda `'self'` e um woff2 do próprio
  bundle passa. Inter é o clone mais próximo de SF Text e dá paridade real de renderização.
  Custa um asset novo no bundle — **e por isso precisa de OK explícito do usuário antes de
  ser implementada.**
- *Sem asset:* manter o stack de sistema e compensar, sob a classe de plataforma Windows, com
  `font-size: 13.5px` e `letter-spacing: -0.006em`, já que Segoe a 13px lê menor e mais leve
  que SF.

**Enquanto a decisão da fonte não vier, implementar a rota sem asset.** Ela é reversível: se
o Inter entrar depois, é uma `@font-face` mais uma entrada no `font-family`.

**Estado de loading.** `<html class="loading">` no `index.html` mais um `<style>` inline no
`<head>` (permitido pela CSP via `style-src 'unsafe-inline'`) que esconde os valores e mostra
a estrutura; `main.ts` remove a classe no `finally` do `load()` — no `finally`, não no `then`,
para que um `invoke()` que falha (por exemplo rodando via `npm run dev`, fora do Tauri) não
deixe a janela travada no estado de loading para sempre.

**Contrato de classes com o SDD-P1-TRAY** — nomes exatos, não sinônimos:

| Classe | Onde | Quem põe | Quem tira |
|---|---|---|---|
| `platform-windows` | `<html>` | `initialization_script` do Rust, sob `#[cfg(windows)]` | ninguém |
| `loading` | `<html>`, estático no HTML | `index.html` | `main.ts`, no `finally` do `load()` |

A classe de plataforma **não** pode ser aplicada pelo `main.ts`: `load()` é async e a classe
chegaria depois do primeiro paint, produzindo um flash de tipografia.

**Alternativas descartadas.**
- *Fluent/WinUI, ou Mica/Acrylic via `tauri.conf.json`* — decisão de produto já tomada: o alvo
  é paridade com o macOS, não integração com o Windows. Rejeitada.
- *`data:` URI de SVG para chevron e check* — bloqueado pela CSP. Rejeitada.
- *Relaxar a CSP com `img-src 'self' data:`* — abre superfície por puro conforto estético.
  Rejeitada.
- *`outline` para o focus ring* — não produz o halo difuso; o Aqua é `box-shadow`. Rejeitada.
- *Aplicar a classe de plataforma no `main.ts`* — flash garantido. Rejeitada.

## Tarefas por owner

```
owner: voxis-ui-dev
arquivo: apps/tray/src/styles.css
ação: reescrever inteiro sobre custom properties (--bg, --fg, --fg-secondary, --separator, --control-bg, --control-border, --accent #007aff/#0a84ff, --accent-ring, --radius-control 6px, sombras), com claro e @media (prefers-color-scheme: dark) declarados literalmente; ZERO color-mix(); appearance:none e redesenho de button/select/input/checkbox/textarea; hairline 0.5px; focus ring como box-shadow difuso de ~3px; ::-webkit-scrollbar com thumb arredondado (borda transparente + background-clip: padding-box) e scrollbar-gutter: stable; ajustes Windows-only sob .platform-windows (font-size 13.5px, letter-spacing -0.006em)
critério_aceite: npm run dev aberto no Edge — todos os controles renderizam desenhados (nenhum widget default do Chromium visível); tab pelos campos mostra o halo Aqua; alternar o tema do SO troca a paleta sem nenhum elemento ilegível; nenhuma ocorrência de "color-mix(" nem de "data:" no arquivo
depende_de: nenhum
```

```
owner: voxis-ui-dev
arquivo: apps/tray/index.html
ação: envolver cada <select> (hoje cinco: dictate-key, noise, orb-archetype, orb-palette, orb-position — reconferir a lista no arquivo) num wrapper para ancorar o chevron via ::after; adicionar class="loading" no <html> e um <style> inline no <head> com o estilo do estado de loading
critério_aceite: o chevron aparece em todo select, com pointer-events:none (clicar sobre ele ainda abre o select); nenhum data: URI no arquivo; com o JS desabilitado no DevTools a página fica no estado de loading, mostrando estrutura e não branco
depende_de: os pseudo-elementos definidos em styles.css
```

```
owner: voxis-ui-dev
arquivo: apps/tray/src/main.ts
ação: remover a classe "loading" do <html> no finally do load() (hoje :185 é load().then(bind)); NÃO aplicar classe de plataforma aqui — isso é o initialization_script do Rust (SDD-P1-TRAY); manter o isWindows existente apenas para lógica (tecla default, modelo STT)
critério_aceite: abrir a janela de settings com o daemon parado (get_settings demora e falha parcialmente) e ainda assim a classe loading sai e a UI fica utilizável; nenhuma classe platform-* é adicionada por JS
depende_de: index.html com a classe loading
```

## Critérios de aceite gerais (prova local, sem CI)

- `npm run dev` + Edge: o `invoke()` falha fora do Tauri e cai no `.catch`, mas o layout e
  todos os controles renderizam — que é exatamente o que se quer inspecionar. Comparar lado a
  lado com um screenshot da janela do macOS.
- Nenhuma violação de CSP no console (`Refused to load the image`, `Refused to apply style`).
- Redimensionar a janela para o mínimo (480x520) sem quebrar o layout — o `max-width: 520px`
  do `main` permanece.
- No MSI, via `voxis-verify-windows`: a janela de configurações abre centralizada, com
  conteúdo visível em menos de ~100ms, e sem flash de tipografia entre o primeiro paint e o
  fim do `load()`.

## Riscos

- **Fonte maior estourando o layout de 560px.** O `min_inner_size(480, 520)` do SDD-P1-TRAY dá
  folga e o `max-width: 520px` do `main` permanece; ainda assim, os rótulos em português são
  longos e 13.5px pode empurrar algum `label` para duas linhas. Verificar com a janela no
  tamanho mínimo.
- **`color-mix()` removido revela dependências implícitas.** É a única fonte de cor derivada
  hoje; qualquer separador que dependia dela precisa de um token literal equivalente nos dois
  esquemas — é fácil deixar um separador invisível no tema escuro.
- **Hairline de 0.5px em telas a 100%.** Numa tela sem DPI fracionário, 0.5px pode ser
  arredondado para 0 (sumir) ou 1 (não é hairline) dependendo do WebView2. Conferir em 100% e
  em 125%, e considerar `transform: scaleY(0.5)` num pseudo-elemento se sumir.
- **Decisão pendente do Inter.** Empacotar uma fonte é asset novo no bundle, ou seja, mudança
  de escopo — precisa de OK do usuário. Até lá, a rota sem asset entrega paridade aproximada,
  não idêntica.
- **O CSS é o mesmo nas duas plataformas por decisão de produto**, então esta reescrita
  **muda a aparência do macOS também**, e ninguém está testando Mac neste fork. O risco é
  contido (o alvo *é* o look do Mac), mas um bug de token no tema escuro apareceria lá
  primeiro e sem observador.
- **Dívida registrada:** `ASSISTANT_MODE` continua sendo setting morto — nada lê `config.MODE`,
  mas o tray o persiste e valida. Esta entrega deixa o controle bonito sem torná-lo funcional.
