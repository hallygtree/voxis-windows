# Architecture: B1 WASAPI Loopback Integration

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    miris CLI (cli.py)                           │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ cmd_start() → spawns recorder.py in detached process    │  │
│  │ cmd_stop()  → sends SIGTERM or creates stop sentinel    │  │
│  │ cmd_doctor()→ platform-aware smoke test (B1-specific)   │  │
│  └──────────────────────────────────────────────────────────┘  │
└────────────────────────────┬─────────────────────────────────────┘
                             │
        ┌────────────────────┴────────────────────┐
        │                                         │
        v                                         v
┌──────────────────────┐              ┌──────────────────────┐
│   recorder.py        │              │  systemtap.py        │
│                      │              │                      │
│ ┌──────────────────┐ │              │ ┌────────────────┐   │
│ │ record()         │ │              │ │ Tap(ABC)       │   │
│ │ ├─ tap_factory  │ │◄─────uses─────│ │ ├─ start()    │   │
│ │ ├─ WavWriter    │ │              │ │ ├─ alive()    │   │
│ │ └─ mic.wav      │ │              │ │ └─ stop()     │   │
│ │                  │ │              │ │                │   │
│ │ main()           │ │              │ │ SystemTap(Tap)│   │
│ │ ├─ PIL checks   │ │              │ │ ├─ audiotap   │   │
│ │ ├─ SIGTERM/INT  │ │              │ │ │  (macOS)    │   │
│ │ └─ stop sentinel│ │              │ │ └─ (Popen)    │   │
│ └──────────────────┘ │              │ │                │   │
│                      │              │ │ default_tap   │   │
│ ┌──────────────────┐ │              │ │ _factory()    │   │
│ │ _default_       │ │              │ │ ├─ Windows:   │   │
│ │  open_stream()  │ │              │ │ │   Loopback  │   │
│ │ ├─ sounddevice  │ │              │ │ │   Tap       │   │
│ │ └─ mic input    │ │              │ │ └─ macOS/Li:  │   │
│ └──────────────────┘ │              │ │   SystemTap  │   │
└──────────────────────┘              └────────────────┘
        │                                   │
        │                                   │
        │            ┌──────────────────────┘
        │            │
        │            v
        │      ┌─────────────────────────────┐
        │      │ loopback_windows.py (NEW)   │
        │      │                             │
        │      │ WindowsLoopbackTap(Tap):    │
        │      │                             │
        │      │ ┌────────────────────────┐  │
        │      │ │ start()                │  │
        │      │ │ ├─ open loopback       │  │
        │      │ │ │  speaker default     │  │
        │      │ │ └─ spawn capture       │  │
        │      │ │    thread              │  │
        │      │ └────────────────────────┘  │
        │      │                             │
        │      │ ┌────────────────────────┐  │
        │      │ │ alive()                │  │
        │      │ │ └─ thread.is_alive()   │  │
        │      │ └────────────────────────┘  │
        │      │                             │
        │      │ ┌────────────────────────┐  │
        │      │ │ stop(grace_s)          │  │
        │      │ │ ├─ set stop_event      │  │
        │      │ │ ├─ join(timeout)       │  │
        │      │ │ └─ close WAV           │  │
        │      │ └────────────────────────┘  │
        │      │                             │
        │      │ ┌────────────────────────┐  │
        │      │ │ _capture_loop()        │  │
        │      │ │ (thread target)        │  │
        │      │ ├─ soundcard.loopback   │  │
        │      │ ├─ 48kHz stereo         │  │
        │      │ ├─ _resample_poly()     │  │
        │      │ │  → 16kHz mono         │  │
        │      │ ├─ write WAV            │  │
        │      │ └─ lock for safety      │  │
        │      │ └────────────────────────┘  │
        │      │                             │
        │      │ _resample_poly(x,1,3):      │
        │      │ ├─ numpy.convolve()         │
        │      │ │  (moving avg LP)         │
        │      │ └─ [::3] decimation        │
        │      │                             │
        │      └─────────────────────────────┘
        │
        │
        v
    ┌────────────────────┐
    │ session_dir/       │
    ├────────────────────┤
    │ mic.wav (16k mono) │
    │                    │
    │ system.wav         │ ◄── NEW (B1)
    │ (16k mono,         │
    │  loopback)         │
    │                    │
    │ recorder.pid       │
    │ recorder.log       │
    │ stop (sentinel)    │ ◄── B2
    └────────────────────┘
