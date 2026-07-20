# SDD-B1 — Miris: captura de áudio do sistema no Windows (WASAPI loopback)

owner: miris-windows-dev
status: pronto para implementar
depende_de: nenhum (mas B2 e B4 consomem o mesmo recorder)

## Contexto

O Miris captura o áudio do sistema por um Core Audio tap macOS-only: `SystemTap`
(subprocesso) spawna `helper/audiotap` (Swift). No Windows esse binário não existe,
então gravar reunião não produz `system.wav`. É o bloqueio de porta #1 do Miris.
O `recorder.py` já grava `mic.wav` in-process via sounddevice e já tem parada limpa;
falta a metade "áudio do sistema" no Windows.

## Objetivo / Não-objetivo

- Objetivo: capturar o áudio do alto-falante default (loopback) no Windows,
  gravando `system.wav` em 16 kHz mono, in-process, com parada limpa integrada ao
  ciclo de vida do recorder.
- Não-objetivo: parada por sentinela (SDD-B2), troca de VAD (SDD-B3), transcriber
  (SDD-B4), packaging (SDD-B2..B8). Não tocar no caminho macOS (segue via audiotap).
  Não implementar seleção de dispositivo custom (só o default).

## Requisitos

1. No Windows, a captura do sistema roda numa thread dentro do processo `recorder`,
   sem subprocesso helper nem binário nativo novo.
2. A saída `system.wav` é 16 kHz mono 16-bit PCM (downsample em numpy no processo),
   mesmo formato de `mic.wav`.
3. A escolha macOS(audiotap subprocess) vs Windows(loopback in-process) é feita por
   uma factory selecionada por plataforma, sem `if platform` espalhado.
4. A captura tem `start()` / `stop(grace)` / `alive()` equivalentes ao `SystemTap`
   atual, para o `recorder.record()` não precisar saber qual backend usa.
5. A parada finaliza o WAV (header/tamanho corretos) — nada de arquivo truncado.
6. A dependência de loopback entra só no `requirements-windows.txt` do Miris.

## Design

Abordagem escolhida (Opção 1 do plano): **WASAPI loopback puro-Python, in-process.**
Introduzir um backend `WindowsLoopbackTap` com a mesma interface do `SystemTap`
(`start/alive/stop`) que grava numa thread lendo o loopback do speaker default e
faz downsample 48k estéreo → 16k mono em numpy antes de escrever o WAV (reusando o
`WavWriter` do recorder ou um writer equivalente). `recorder.record()` passa a
receber o tap via factory `tap_factory` já existente (assinatura
`Callable[[Path], Tap]`), e a seleção macOS/Windows vive num
`default_tap_factory()` platform-aware.

Biblioteca: decidir entre `soundcard` (cffi puro, grava loopback do speaker default)
e `pyaudiowpatch` (fork PyApio com WASAPI loopback). Critério: qual empacota limpo
no PyInstaller onedir sem DLL faltando e lida melhor com formato do dispositivo.
Recomendação inicial: `soundcard` (sem extensão nativa custom, cffi resolve DLLs do
sistema); cair para `pyaudiowpatch` se o loopback do default device falhar.

Alternativas descartadas:
- Opção 2 (helper nativo Rust cpal / C# NAudio espelhando `audiotap <out.wav>`):
  mantém o modelo subprocesso 1:1 com macOS mas adiciona toolchain + binário à CI e
  eventual assinatura. Só se quisermos isolar áudio do Python. Rejeitada por custo.
- Capturar em 48k e resample via torchaudio: reintroduz torch no bundle torch-free.
  Rejeitada — downsample em numpy (decimação/polyphase) é suficiente para STT 16k.

## Tarefas por item

```
owner: miris-windows-dev
arquivo: packages/miris/miris/systemtap.py
ação: extrair uma interface Tap (start/alive/stop) e manter SystemTap (audiotap subprocess, macOS) como uma das implementações; adicionar default_tap_factory() que retorna SystemTap no macOS e WindowsLoopbackTap no Windows
critério_aceite: em macOS a factory retorna SystemTap (comportamento atual intacto); em Windows retorna o backend loopback; interface uniforme consumida pelo recorder
depende_de: nenhum
```

```
owner: miris-windows-dev
arquivo: packages/miris/miris/loopback_windows.py
ação: criar WindowsLoopbackTap(out_wav): thread que abre o loopback do speaker default via soundcard (ou pyaudiowpatch), lê frames, downsample->16k mono em numpy, escreve PCM16 no out_wav; start() inicia a thread, stop(grace) sinaliza parada e faz join+finaliza WAV, alive() reflete a thread
critério_aceite: capturar 3s tocando um áudio no sistema produz system.wav 16k mono com bytes > 44 (header) e conteúdo audível; parar não deixa WAV truncado nem thread órfã
depende_de: escolha soundcard vs pyaudiowpatch
```

```
owner: miris-windows-dev
arquivo: packages/miris/miris/recorder.py
ação: trocar o default de tap_factory de SystemTap para systemtap.default_tap_factory (mantendo o parâmetro injetável para testes); nenhuma mudança no fluxo de mic.wav
critério_aceite: record() no Windows usa o loopback tap sem passar tap_factory explícito; testes que injetam um fake tap seguem passando
depende_de: systemtap.py factory; loopback_windows.py
```

```
owner: miris-windows-dev
arquivo: packages/miris/requirements-windows.txt
ação: criar arquivo torch-free com faster-whisper, sounddevice, numpy + a lib de loopback escolhida (soundcard ou pyaudiowpatch); sem torch/torchaudio/silero-vad/mlx/pyobjc
critério_aceite: `pip install -r requirements-windows.txt` num venv limpo Windows instala sem puxar torch; loopback importável
depende_de: escolha da lib
```

## Critérios de aceite (voxis-verify-windows / prova local)

- `miris doctor` (adaptado no B2..B8) reporta o smoke de system-audio ok no Windows.
- Gravar reunião, tocar um áudio no sistema por alguns segundos, parar: `system.wav`
  existe, é 16 kHz mono, tem conteúdo (não só header) e é legível por `wave`.
- Nenhuma thread de captura sobrevive ao `stop()` (sem vazamento).
- `mic.wav` e `system.wav` têm o mesmo sample rate (16k) para o merge do pipeline.

## Riscos

- Troca de dispositivo default no meio da gravação: soundcard/pyaudiowpatch podem
  parar de entregar frames. Decidir se re-abre o stream ou aceita degradação;
  documentar o comportamento.
- Formato do dispositivo (48k estéreo float32 vs int16): normalizar sempre para
  16k mono float→PCM16; testar com placas que só oferecem 44.1k.
- Empacotamento PyInstaller: `soundcard`/`pyaudiowpatch` trazem DLLs/backends que
  o hook estático pode não coletar — coordenar com o SDD de packaging (B2..B8) para
  `collect_all` da lib escolhida.
- Loopback silencioso quando não há áudio tocando: `system.wav` fica quase-vazio;
  o pipeline já tolera canal vazio (guard de WAV_HEADER_BYTES), mas validar.
