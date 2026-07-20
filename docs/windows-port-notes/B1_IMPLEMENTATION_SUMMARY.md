# B1 Implementation Summary: WASAPI Loopback Audio Capture

## Status
**Implementado** - Captura de áudio do sistema via WASAPI loopback in-process no Windows

## Arquivos criados/modificados

### 1. `packages/miris/miris/systemtap.py`
- **Mudança**: Refatorado para introduzir interface abstrata `Tap`
- **Novo**: Classe abstrata `Tap` com métodos `start()`, `alive()`, `stop()`
- **Novo**: `SystemTap` agora implementa `Tap` (mantém comportamento macOS com audiotap subprocess)
- **Novo**: Função `default_tap_factory()` que seleciona a implementação por plataforma:
  - Windows (`sys.platform == "win32"`): retorna `WindowsLoopbackTap`
  - macOS/Linux: retorna `SystemTap`

### 2. `packages/miris/miris/loopback_windows.py` (NOVO)
- **Classe**: `WindowsLoopbackTap(Tap)`
- **Implementação**:
  - Captura loopback do speaker default via `soundcard` library
  - Roda em thread background (não bloqueia recorder principal)
  - Downsample de 48 kHz estéreo → 16 kHz mono via numpy (sem scipy)
  - Escreve 16-bit PCM WAV incrementalmente (thread-safe)
  - Parada limpa: finaliza WAV corretamente (sem truncamento)
- **Interface**:
  - `start()`: Inicia thread de captura
  - `alive()`: Verifica se thread está rodando
  - `stop(grace_s=5.0)`: Para captura e finaliza WAV

### 3. `packages/miris/miris/recorder.py`
- **Mudança**: Atualizado para usar `Tap` e `default_tap_factory()`
- **Import**: Mudou de `SystemTap` para `Tap, default_tap_factory`
- **Assinatura**: `tap_factory` agora é `Callable[[Path], Tap] | None = None`
- **Comportamento**: Se `tap_factory is None`, usa `default_tap_factory()` automaticamente
- **Compatibilidade**: Testes que injetam `tap_factory` customizado continuam funcionando

### 4. `packages/miris/requirements-windows.txt` (NOVO)
- **Dependências torch-free**:
  - numpy>=1.24.0
  - sounddevice>=0.4.6
  - soundcard>=0.4.6 (WASAPI loopback)
  - laris (transcription via faster-whisper)
  - pytest>=8.0.0 (dev)
- **Excluídos**:
  - torch, torchaudio (usar faster-whisper via onnxruntime)
  - silero-vad (usar VAD embutido do faster-whisper)
  - mlx, pyobjc (macOS-only)

### 5. `packages/miris/tests/test_loopback_windows.py` (NOVO)
- Testes unitários para `WindowsLoopbackTap`
- Validam:
  - Interface `Tap` implementada
  - Lifecycle start/alive/stop
  - Graceful shutdown
  - Detecção de erros de hardware gracefully

## Critérios de Aceite Implementados

✅ Interface uniforme `Tap` - `start()`, `alive()`, `stop()` equivalentes
✅ Captura in-process em thread (sem subprocesso helper nativo)
✅ Saída 16 kHz mono 16-bit PCM (downsampled em numpy)
✅ Factory platform-aware sem `if platform` espalhado no código
✅ Parada limpa com finalização correta de WAV
✅ Dependências torch-free em `requirements-windows.txt`

## Próximas dependências (B2-B8)

Após validação de B1 com `voxis-verify-windows`, priorize:

1. **B2 (Parada via sentinela)**: `packages/miris/miris/cli.py::cmd_stop` usa arquivo sentinela
2. **B3 (VAD embutido)**: `packages/miris/miris/transcribe.py` usa `faster-whisper` VAD (onnxruntime)
3. **B4 (Transcriber default)**: `packages/miris/miris/pipeline.py` usa `FasterWhisperTranscriber`
4. **B5-B8**: Requerem coordenação com `tray-dev` (Rust) ou são passthrough

## Como testar localmente

```bash
# Instalar dependências torch-free
pip install -r packages/miris/requirements-windows.txt

# Rodar testes unitários
pytest packages/miris/tests/test_loopback_windows.py -v
pytest packages/miris/tests/test_recorder.py -v

# Teste de integração (com áudio real):
# Veja voxis-verify-windows para gravar sessão real e validar system.wav
```

## Riscos conhecidos

1. **Dispositivo loopback indisponível**: Se o speaker default não tiver loopback habilitado (Stereo Mix desativado), `start()` falhará. O erro é capturado e retornado como aviso em `_capture_loop()`.
2. **Troca de dispositivo em runtime**: Se o speaker default mudar durante gravação, o stream atual não se readapta. Documentado como degradação aceitável (raro em reuniões).
3. **Formato do dispositivo variável**: Normalmente 48 kHz estéreo float32, mas pode variar por placa de som. Código normaliza para 16 kHz mono float→int16.
4. **Empacotamento PyInstaller**: `soundcard` + CFFI + backends podem exigir `collect_all` explícito; coordenar com SDD de packaging.

## Notas de implementação

- Downsample usa simple moving-average low-pass (sem scipy) + decimation
- WAV header é escrito na abertura (wave.py preenche automático)
- Lock mutex evita race condition entre thread de captura e `stop()`
- Thread é non-daemon (`daemon=False`) para garantir finalização antes de `stop()` retornar
