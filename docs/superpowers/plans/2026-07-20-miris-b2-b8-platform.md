# SDD-B2..B8 — Miris: parada por sentinela, VAD, transcriber, packaging, detach, llm

owner: miris-windows-dev
status: pronto para implementar
depende_de: SDD-B1 (recorder/loopback) para o smoke ponta a ponta

## Contexto

Depois do B1 (captura), o Miris ainda tem cinco bloqueios de plataforma no Windows:
o `os.kill(SIGTERM)` vira `TerminateProcess` e não finaliza o WAV (B2); o pipeline
depende de `torch`/`silero_vad` para VAD, excluídos do bundle torch-free (B3); o
transcriber default é mlx (B4); o spawn detach `-m miris.recorder` não funciona
congelado (B7); e o `llm_command` (`.cmd` shim do npm) não resolve via
`subprocess.run` sem extensão (B8). Além disso falta empacotar o `miris-engine`.

## Objetivo / Não-objetivo

- Objetivo: tornar o ciclo start→gravar→stop→transcrição→nota funcional no Windows
  congelado, torch-free, com parada limpa e LLM resolvível; e empacotar o
  `miris-engine.exe` via PyInstaller espelhando o Laris.
- Não-objetivo: captura de áudio (SDD-B1), resolução tray-side do `miris_bin` e
  `pid_alive` (SDD-Tray), assinatura de código, seleção de dispositivo de áudio.

## Requisitos

1. (B2) Parada do recorder por **arquivo-sentinela**: `cmd_stop` cria o sentinela;
   o recorder faz poll e encerra graciosamente, finalizando ambos os WAVs. Sem
   depender de SIGTERM no Windows.
2. (B2) O caminho macOS (SIGTERM) permanece funcional (ou converge para o mesmo
   mecanismo de sentinela, se mais simples e cross-plat).
3. (B3) A detecção de fala (VAD) usa o **VAD embutido do faster-whisper** (Silero
   via onnxruntime, já bundlado), sem `torch`/`silero_vad`.
4. (B3) `load_wav_mono16k` não importa torch/torchaudio: como a captura já é 16k
   (B1), o caminho de resample torch é eliminado (erro claro se sr != 16k em vez
   de importar torch).
5. (B4) No Windows, o transcriber default é `laris.stt_faster.FasterWhisperTranscriber`
   (interface `.transcribe()`/`.warm()` compatível), não o mlx `Transcriber`.
6. (B7) Congelado, `cmd_start` spawna o recorder via subcomando interno do próprio
   exe (`__recorder <session>`), não `-m miris.recorder`; detach Windows via
   `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS`.
7. (B8) `llm_command` é resolvido via `shutil.which` antes de `subprocess.run`,
   cobrindo `.cmd`/`.exe` shims sem `shell=True`.
8. `packaging/{miris.spec,entry.py}` produzem um `miris-engine` onedir torch-free
   que despacha `start|stop|status|retry|doctor` + o interno `__recorder`.
9. O CI buildar o `miris-engine` no job windows-latest e stageá-lo em
   `apps/tray/src-tauri/engine-miris/`; `tauri.windows.conf.json` bundla o recurso.

## Design

B2 — sentinela cross-plat: `cmd_stop` escreve `session/stop` (ou toca um
`stop.flag`); `recorder.main()` roda um poll (ex.: 200ms) que seta o `threading.Event`
quando o sentinela aparece, além dos handlers de sinal (mantidos no macOS). Isso
substitui a dependência de sinal no Windows, onde `TerminateProcess` mataria antes
de `finally` finalizar o WAV. `cmd_stop` aguarda o `recorder.pid` sumir (já existe
o loop de espera) e então roda o pipeline.

B3 — VAD faster-whisper: remover `speech_spans` (silero+torch) do caminho quente.
`FasterWhisperTranscriber.transcribe()` já pode receber o áudio inteiro do canal com
`vad_filter=True` do WhisperModel, delegando a segmentação ao VAD Silero-onnx
embutido. `transcribe_channel` é reestruturado para consumir os `Segment` do
faster-whisper (com `start/end` próprios) em vez de fatiar por spans externos, e
mapear para o `Segment` local (start_s/end_s/speaker/text) preservando o timeline
do `merge()`. `load_wav_mono16k` deixa de importar torch: se `sr != 16k`, erro
explícito (a captura B1 garante 16k).

B4 — factory platform-aware em `pipeline._default_transcriber_factory`: no Windows
retorna `FasterWhisperTranscriber`, no macOS mantém `laris.transcriber.Transcriber`.
Ambos expõem `.transcribe()`/`.warm()` (confirmado em stt_faster.py). Mantém
`STT_LANGUAGE=""` (auto-detect bilíngue).

B7 — `entry.py` do miris despacha subcomandos; quando `sys.frozen`, `cmd_start`
spawna `[sys.executable, "__recorder", session]` com
`creationflags=CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS`; fora de frozen mantém
`-m miris.recorder` + `start_new_session=True`.

B8 — `notes.generate` e `cmd_doctor` resolvem `cfg.llm_command[0]` via
`shutil.which` (respeitando PATHEXT p/ `.cmd`), substituindo o executável pelo path
absoluto antes do `subprocess.run`; se `which` falhar, `NotesError` clara.

Packaging — `miris.spec` espelha `laris.spec`: `collect_all` das deps nativas
(faster_whisper, ctranslate2, av, onnxruntime, sounddevice + a lib de loopback do
B1), `collect_submodules("miris")` e `collect_submodules("laris")` (reusa
`laris.stt_faster`), `pathex` absoluto via SPECPATH, mesmos `excludes`
(torch/mlx/pyobjc/silero_vad). `entry.py` roteia subcomandos.

Alternativas descartadas:
- Manter silero_vad standalone via onnxruntime (sem torch): possível, mas duplica o
  VAD que o faster-whisper já embute. Rejeitada — reusar o `vad_filter`.
- Sinal `CTRL_BREAK_EVENT` para parar o recorder no Windows em vez de sentinela:
  exige grupo de processo e é frágil com processos detached/frozen. Sentinela é
  determinística e cross-plat. Rejeitada.
- `shell=True` para resolver o `.cmd`: injeção + quoting frágil. `shutil.which` é
  seguro. Rejeitada.

## Tarefas por item

```
owner: miris-windows-dev
arquivo: packages/miris/miris/recorder.py
ação: (B2) em main(), além dos handlers SIGTERM/SIGINT, iniciar um poll de sentinela (session/"stop") que seta o stop Event; garantir finalização dos WAVs no finally mesmo sem sinal; (B7) expor um entrypoint chamável pelo subcomando __recorder
critério_aceite: criar session/"stop" faz o recorder encerrar e finalizar mic.wav+system.wav íntegros no Windows sem sinal POSIX
depende_de: SDD-B1 (record/tap)
```

```
owner: miris-windows-dev
arquivo: packages/miris/miris/cli.py
ação: (B2) cmd_stop cria o sentinela session/"stop" antes de esperar o pid sumir (mantendo os.kill no macOS como fallback); (B7) cmd_start, quando sys.frozen, spawna [sys.executable,"__recorder",session] com creationflags CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS no Windows, senão -m miris.recorder+start_new_session; (B8) cmd_doctor resolve llm via shutil.which
critério_aceite: `miris start`/`stop` congelado no Windows grava e finaliza a sessão; doctor resolve o llm_command shim .cmd
depende_de: recorder.py sentinela; entry.py subcomando
```

```
owner: miris-windows-dev
arquivo: packages/miris/miris/transcribe.py
ação: (B3) reescrever speech_spans/transcribe_channel para usar vad_filter do faster-whisper (consumir Segments com start/end nativos e mapear para Segment local); load_wav_mono16k deixa de importar torch e erra claro se sr!=16k
critério_aceite: transcrever mic.wav/system.wav 16k produz Segments com timeline coerente sem importar torch nem silero_vad; merge() ordena por start_s como hoje
depende_de: SDD-B4 (transcriber que expõe segmentos VAD)
```

```
owner: miris-windows-dev
arquivo: packages/miris/miris/pipeline.py
ação: (B4) _default_transcriber_factory retorna FasterWhisperTranscriber no Windows e Transcriber(mlx) no macOS; manter STT_LANGUAGE="" default; build_transcript inalterado no restante
critério_aceite: no Windows o pipeline usa faster-whisper (sem import mlx); .warm() e .transcribe() são chamados como hoje
depende_de: transcribe.py consumir segmentos do faster-whisper
```

```
owner: miris-windows-dev
arquivo: packages/miris/miris/notes.py
ação: (B8) em generate(), resolver cfg.llm_command[0] via shutil.which (PATHEXT-aware) e usar o path absoluto no subprocess.run; NotesError clara se não resolver
critério_aceite: um llm_command=["agy",...] cujo agy é agy.cmd resolve e roda; comando inexistente vira NotesError legível
depende_de: nenhum
```

```
owner: miris-windows-dev
arquivo: packages/miris/packaging/entry.py
ação: criar entrypoint que faz argparse de start|stop|status|retry|doctor e do interno __recorder <session>; __recorder chama recorder.main-equivalent com o session_dir
critério_aceite: `miris-engine __recorder <dir>` roda o loop de gravação; `miris-engine status` etc funcionam congelados
depende_de: recorder.py entrypoint
```

```
owner: miris-windows-dev
arquivo: packages/miris/packaging/miris.spec
ação: espelhar laris.spec: sys.path.insert do SPECPATH.parent, pathex absoluto, collect_all das deps nativas + lib de loopback, collect_submodules("miris")+("laris"), excludes torch/mlx/pyobjc/silero_vad; EXE name miris-engine, console=False, COLLECT onedir
critério_aceite: `pyinstaller packaging/miris.spec --noconfirm` gera dist/miris-engine/ sem ModuleNotFoundError; import de miris e laris.stt_faster resolvem
depende_de: entry.py; requirements-windows.txt (SDD-B1)
```

```
owner: miris-windows-dev
arquivo: .github/workflows/tray-build.yml
ação: no job windows-latest, após o build do laris, adicionar passo que instala miris (pip install -e . + requirements-windows.txt + pyinstaller), roda o miris.spec e copia dist/miris-engine/* para apps/tray/src-tauri/engine-miris/
critério_aceite: artefato Windows contém engine-miris/miris-engine.exe
depende_de: miris.spec
```

```
owner: miris-windows-dev
arquivo: apps/tray/src-tauri/tauri.windows.conf.json
ação: acrescentar "engine-miris/" ao mapa de resources do bundle (junto de engine/)
critério_aceite: instalador Windows empacota engine-miris/ no resource_dir; nota: a resolução do miris_bin e do pid_alive é do SDD-Tray
depende_de: nenhum (coordenar com SDD-Tray)
```

## Critérios de aceite (voxis-verify-windows / prova local)

- `miris doctor` (congelado) passa: loopback ok, vault ok, llm resolvido, smoke 3s.
- Fluxo completo: "Gravar reunião" → tocar áudio → "Parar" → nota criada no vault,
  abre em "Última nota"; `mic.wav`/`system.wav` válidos, `transcript.md` populado.
- Nenhum import de `torch`/`silero_vad`/`mlx` no processo miris-engine (grep no
  traceback/log ou `--debug imports` do PyInstaller).
- Parar a gravação nunca deixa WAV truncado (sentinela finaliza no `finally`).

## Riscos

- **B3/VAD — RISCO ABERTO, parcialmente resolvido (2026-07-20).**
  - *Resolvido, com evidência:* o timeline de `merge()` continua coerente. Com
    `vad_filter=True` o faster-whisper chama `restore_speech_timestamps`
    (`faster_whisper/transcribe.py:1010`), então `segment.start`/`.end` já vêm
    na timeline do áudio **original**, em segundos — não em índices de amostra
    do trecho filtrado. `transcribe_channel` repassa esses valores direto, e há
    teste cobrindo o mapeamento e a intercalação dos dois canais
    (`test_transcribe.py::test_transcribe_channel_prefers_builtin_vad_and_keeps_its_timestamps`,
    `::test_vad_segments_merge_into_a_coherent_two_speaker_timeline`).
  - *NÃO validado:* a **granularidade**. Os `Segment` do faster-whisper são
    segmentos do decoder (janelas de até ~30 s, tipicamente por frase), enquanto
    o silero devolvia spans por elocução. O transcript intercalado fica mais
    grosso: turnos curtos de "Eles" que caíam entre duas falas de "Eu" podem
    agora aparecer agrupados fora de ordem de conversa (a ordenação por
    `start_s` continua correta, a *legibilidade* do diálogo é que muda). Isso é
    o que o LLM resume, então afeta a nota final.
  - *Por que não foi validado:* exige áudio real de reunião bilíngue (pt-BR/EN)
    com dois canais; não há corpus no repo e não dá para sintetizar fala com
    fidelidade suficiente para julgar corte de frase.
  - *Como fechar:* rodar o item "Reuniões" da skill `voxis-verify-windows` com
    uma reunião real e comparar `transcript.md` com o áudio. Se cortar frases ou
    agrupar demais, ajustar `vad_parameters` (`min_silence_duration_ms`,
    `threshold`) na chamada de `transcribe_with_vad` em
    `packages/laris/laris/stt_faster.py`.
- **Resample no macOS trocou de implementação (2026-07-20).** Para tirar o torch
  do caminho quente, `load_wav_mono16k` deixou de usar `torchaudio.functional.
  resample` e passou a usar `miris.audio.resample_to_16k` (numpy, média de
  blocos) — em **ambas** as plataformas. O macOS precisa desse caminho: o
  `audiotap.swift` grava `system.wav` na taxa nativa do dispositivo
  (`mSampleRate: asbd.mSampleRate`, tipicamente 48 kHz), então remover o
  resample teria feito toda reunião no macOS perder o canal do sistema em
  silêncio (`build_transcript` engole erro por canal).
  Resposta medida do filtro boxcar de 3 taps no 48k→16k: −0.1 dB @1 kHz,
  −0.9 dB @4 kHz, −3.9 dB @8 kHz, null em 16 kHz, −14.9 dB @20 kHz. Adequado
  para STT (a banda que importa para o Whisper fica abaixo de 4 kHz) e muito
  melhor que a decimação sem filtro que estava no loopback, mas mais fraco que
  o sinc janelado do torchaudio. *Não validado em macOS* — não há macOS nesta
  máquina. Se aparecer degradação de transcrição no macOS, é o primeiro
  suspeito.
- Sentinela vs pid: garantir ordem — `cmd_stop` cria o sentinela e só então espera
  o pid sumir; corrida se o recorder ainda não escreveu o pid.
- Detach frozen: `DETACHED_PROCESS` sem console pode engolir stderr do recorder;
  manter o redirecionamento para `recorder.log` como hoje.
- Packaging da lib de loopback: DLLs de soundcard/pyaudiowpatch podem faltar no
  onedir — usar `collect_all` da lib e testar o exe num Windows sem Python.
- `shutil.which` depende de PATH do processo; GUI/tray-spawned pode ter PATH
  reduzido — considerar herdar o PATH do usuário ou aceitar path absoluto no
  `llm_command`.
