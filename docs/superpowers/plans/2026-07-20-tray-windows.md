# SDD-Tray-Windows — tray: pid_alive real, miris_bin congelado, stop gracioso

owner: tray-dev
status: pronto para implementar
depende_de: SDD-B2..B8 (bundle engine-miris existir para o smoke); A2 (stop) pode
ser feito junto ou aqui — ver nota

## Contexto

As pontas Rust/Tauri que consomem os engines ainda assumem macOS. (B5) `pid_alive`
no Windows é `#[cfg(not(unix))] -> false`, então o tray nunca detecta gravação em
curso. (B6) `miris_bin` default aponta para `~/.local/bin/miris`, inexistente sem
Python — o tray precisa resolver o `miris-engine.exe` bundlado como já faz com o
`laris-engine.exe`. E o encerramento do engine Laris no Windows congela 3s (A2, aqui
consolidado do lado Rust).

## Objetivo / Não-objetivo

- Objetivo: no Windows, o tray detecta a gravação do Miris por pid real, resolve o
  `miris-engine.exe` congelado do resource_dir (fallback ao path configurado), e
  encerra o daemon Laris sem freeze.
- Não-objetivo: qualquer Python (é do laris/miris-dev), captura de áudio, VAD,
  packaging Python. A UI de settings (tecla/modelo) é do SDD-A2/A3 — aqui só o
  encerramento gracioso do lado Rust, se não coberto lá.

## Requisitos

1. (B5) `pid_alive(pid)` no Windows retorna `true` sse o processo existe e está
   vivo, `false` caso contrário — via API Win32 (OpenProcess + GetExitCodeProcess
   == STILL_ACTIVE, ou equivalente do crate já disponível).
2. (B5) O contrato read-only de `status()` é preservado: o tray nunca mata nem
   limpa pidfiles; só lê.
3. (B6) No Windows, `config.miris_bin` resolve para
   `<resource_dir>/engine-miris/miris-engine.exe` quando existir; senão cai para o
   `miris_bin` de `tray.json` (comportamento atual).
4. (B6) A resolução espelha a do laris-engine (mesmo padrão em `lib.rs::setup`).
5. (A2) `LarisDaemon::stop` no Windows encerra imediatamente (sem loop de 3s),
   mantendo o caminho unix intacto.
6. Testes Rust cross-plat continuam verdes; os testes hoje `#[cfg(unix)]` para
   `pid_alive`/lifecycle ganham cobertura Windows onde fizer sentido.

## Design

B5 — implementar `#[cfg(windows)] fn pid_alive(pid: i32) -> bool` usando Win32:
`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, ...)` + `GetExitCodeProcess`, tratando
`STILL_ACTIVE` como vivo e fechando o handle. Preferir o `windows`/`windows-sys`
crate se já estiver no árvore de deps do tauri; senão avaliar `sysinfo`. O guard de
`pid > 0` em `status()` já existe e permanece.

B6 — em `lib.rs::setup`, adicionar um bloco `#[cfg(windows)]` análogo ao do laris:
resolver `app.path().resource_dir()?.join("engine-miris").join("miris-engine.exe")`,
e se existir sobrescrever `config.miris_bin` com esse path antes do `app.manage`.
Isso mantém o `TrayConfig::default` (`~/.local/bin/miris`) como fallback para dev.

A2 (consolidado) — `LarisDaemon::stop` ganha `#[cfg(windows)]` com
`child.kill()`+`wait()` imediato. (Se o SDD-A2/A3 já entregar isso via tray-dev,
esta tarefa é a mesma — não duplicar; referenciar.)

Alternativas descartadas:
- `pid_alive` via rodar `tasklist`/CLI: caro e frágil de parsear; API Win32 é O(1)
  e sem shell. Rejeitada.
- Setar `miris_bin` no `TrayConfig::default` condicional a Windows: não tem acesso
  ao `resource_dir` (só o AppHandle no setup tem). Resolver no `setup` é o lugar
  certo, espelhando o laris. Rejeitada a via default().
- Detectar gravação chamando `miris status` (CLI): segundos de import Python por
  tick de 2s — o próprio comentário do módulo veta. Manter leitura direta do
  sessions dir. Rejeitada.

## Tarefas por item

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/miris.rs
ação: (B5) substituir o `#[cfg(not(unix))] pid_alive -> false` por um `#[cfg(windows)]` que consulta o SO (OpenProcess+GetExitCodeProcess==STILL_ACTIVE via windows-sys, ou sysinfo); manter o guard pid>0 e o contrato read-only; adicionar teste Windows análogo ao status_recording_with_live_pid usando o próprio pid
critério_aceite: status() num Windows com um recorder.pid vivo retorna Recording{session,pid}; pid morto/corrupto retorna Idle sem apagar pidfile; testes cargo verdes em windows-latest
depende_de: nenhum
```

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/lib.rs
ação: (B6) em setup(), no bloco #[cfg(windows)], resolver resource_dir()/engine-miris/miris-engine.exe; se existir, atribuir a config.miris_bin antes do app.manage(AppState); senão manter o valor de tray.json
critério_aceite: numa instalação Windows com o bundle, miris start/stop usam o exe congelado (não ~/.local/bin/miris); sem o bundle, cai no fallback configurado
depende_de: SDD-B2..B8 (engine-miris no resource_dir); tauri.windows.conf.json com engine-miris/
```

```
owner: tray-dev
arquivo: apps/tray/src-tauri/src/laris.rs
ação: (A2) adicionar caminho #[cfg(windows)] em LarisDaemon::stop com child.kill()+child.wait() imediato, mantendo o #[cfg(unix)] SIGTERM+grace; consolida a tarefa de mesmo nome do SDD-A2/A3 (não duplicar se já feito lá)
critério_aceite: stop no Windows retorna sem o loop de 3s; lifecycle test unix intacto
depende_de: nenhum
```

## Critérios de aceite (voxis-verify-windows / prova local)

- Iniciar "Gravar reunião" no Windows: dentro de ~2s o menu do tray reflete
  "gravando" (pid_alive real detecta o recorder).
- Parar a gravação: o tray volta a Idle; nenhuma pidfile é apagada pelo tray.
- `miris start` disparado pelo tray executa `engine-miris/miris-engine.exe`
  (verificável no Process Explorer / log), não um path Python inexistente.
- Toggle-off e "Sair" do ditado não congelam o tray por 3s.

## Riscos

- Escolha do crate Win32: se `windows-sys` não estiver no lockfile do tauri, evitar
  inflar deps; `sysinfo` é mais pesado mas ergonômico. Decidir por menor superfície.
- `GetExitCodeProcess` tem a armadilha do código 259 (STILL_ACTIVE): um processo que
  saiu com código 259 pareceria vivo. Usar `WaitForSingleObject(handle, 0)` como
  desempate se necessário.
- Reuso de PID pelo SO: um pidfile stale cujo número foi reciclado por outro
  processo daria falso-positivo de "gravando". Baixo risco no intervalo curto entre
  sessões; documentar. O guard read-only impede que o tray "conserte" errado.
- Ordem de dependência: o teste de fumaça do miris só passa com o bundle engine-miris
  (SDD-B2..B8) presente; até lá, o fallback de miris_bin evita crash.
