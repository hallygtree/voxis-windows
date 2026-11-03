---
name: voxis-verify-windows
description: Roteiro de smoke test clean-room para o fork Voxis-Windows — desinstalar versão atual, limpar %LOCALAPPDATA%\VOXIS e ~/.config/voice-at, instalar do zero, testar ditado (Laris) e reuniões (Miris), inspecionar laris-engine.log. Use sempre depois de um build verde de [[voxis-build-windows]], ou quando o usuário disser que algo "não funciona" no Windows e for preciso reproduzir do zero como usuário novo.
---

# Voxis Verify (Windows, clean-room)

Aplique [[voxis-token-lean]]: reporte só o que falhou, não narre cada passo
que funcionou como esperado. O hook global do RTK já comprime a saída de todo
comando Bash desta sessão; para os passos de PowerShell abaixo, quando abrir
um shell fora do hook, prefixe com `rtk` mesmo assim (`rtk Get-Content ...`).

## Passos

1. Desinstalar: rodar `uninstall.exe` do VOXIS atual (Painel de Controle ou
   `%LOCALAPPDATA%\VOXIS\uninstall.exe`).
2. Apagar estado residual:
   - `rtk Remove-Item -Recurse -Force "$env:LOCALAPPDATA\VOXIS"`
   - `rtk Remove-Item -Recurse -Force "$HOME\.config\voice-at"`
3. Instalar o artefato novo (`.msi`/`.exe` de `voxis-build-windows`).
4. Conceder microfone em Configurações > Privacidade > Microfone (o instalador
   não faz isso sozinho).
5. **Ditado (Laris):**
   - Abrir um app de texto qualquer, segurar `Right Shift`, falar, soltar.
   - Confirmar: texto aparece no app em foco; orb reage (aparece/anima).
   - `rtk grep -iE "traceback|modulenotfounderror" ~/.config/voice-at/laris-engine.log`
     — não pode dar match. Se der, é regressão do fix A1.
   - Conferir `peers.json` em `~/.config/voice-at/` existe e tem porta viva.
6. **Reuniões (Miris)** — só depois que a Parte B (port Windows) existir:
   - Tray → "Gravar reunião"; tocar áudio no sistema (YouTube, etc.); "Parar
     gravação".
   - Confirmar: nota criada no vault, abre em "Última nota".
   - Conferir arquivos da sessão: `mic.wav` e `system.wav` não-vazios e
     abrem em player; `transcript.md` populado com texto plausível.
7. Reportar ao usuário: PASS/FAIL por item, e para cada FAIL o trecho de log
   relevante (nunca o log inteiro).

## Sinal de regressão rápida

Se o toggle de ditado "liga" mas nada acontece ao segurar a tecla, e o log
mostra `ModuleNotFoundError: No module named 'laris'` — o fix A1
(`packages/laris/packaging/laris.spec`) não foi aplicado ou o build usado é
antigo. Não investigue mais nada até confirmar isso primeiro.
