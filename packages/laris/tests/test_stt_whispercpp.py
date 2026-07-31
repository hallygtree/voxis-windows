"""whisper.cpp transcriber: backend-selection chain (mocked) and the contract
clauses miris and daemon.run depend on.

The selection chain is the part worth guarding: it decides between a discrete
GPU, an integrated one, the Parakeet CPU fallback and Whisper on CPU, and every
rung has a different failure mode that used to be invisible in a windowed exe.
"""
import wave
import io

import numpy as np
import pytest

from laris import whispercpp_runtime as runtime

# Captured at import: the autouse fixture below stubs runtime.vulkan_devices so
# the construction tests see "no GPU", but the caching tests need the real one.
_REAL_VULKAN_DEVICES = runtime.vulkan_devices

# verbatim from `whisper-cli --help` on a laptop with both an iGPU and a dGPU
BANNER = """ggml_vulkan: Found 2 Vulkan devices:
ggml_vulkan: 0 = Intel(R) Iris(R) Xe Graphics (Intel Corporation) | uma: 1 | fp16: 1 | bf16: 0
ggml_vulkan: 1 = NVIDIA GeForce RTX 3050 Laptop GPU (NVIDIA) | uma: 0 | fp16: 1 | bf16: 1
"""

DGPU = runtime.VulkanDevice(1, "NVIDIA GeForce RTX 3050 Laptop GPU (NVIDIA)", False)
IGPU = runtime.VulkanDevice(0, "Intel(R) Iris(R) Xe Graphics (Intel Corporation)", True)


class FakeServer:
    """Stands in for whisper-server. Records what it was built for."""
    instances = []

    def __init__(self, model, device, language):
        self.model, self.device, self.language = model, device, language
        self.started = self.stopped = False
        self.payload = {"text": " ola mundo ", "segments": [
            {"start": 0.0, "end": 1.0, "text": " ola"},
            {"start": 1.0, "end": 2.0, "text": " mundo"},
            {"start": 2.0, "end": 3.0, "text": "   "},   # blank: must be dropped
        ]}
        FakeServer.instances.append(self)

    def start(self):
        self.started = True

    def infer(self, wav, verbose):
        return self.payload

    def stop(self):
        self.stopped = True


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """No real binaries, no real downloads, no real subprocesses - and no
    writes to the user's actual ~/.config/voice-at."""
    FakeServer.instances = []
    monkeypatch.setenv("VOXIS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(runtime, "ensure_model", lambda spec: f"/models/{spec.filename}")
    monkeypatch.setattr(runtime, "WhisperServer", FakeServer)
    monkeypatch.setattr(runtime, "vulkan_devices", lambda: [])


def _make(monkeypatch, devices=(), language="pt", allow_parakeet=True):
    import laris.stt_whispercpp as mod
    from laris import config
    monkeypatch.setattr(runtime, "vulkan_devices", lambda: list(devices))
    monkeypatch.setattr(config, "STT_LANGUAGE", language)
    return mod.WhisperCppTranscriber(allow_parakeet=allow_parakeet)


def test_device_parsing_reads_the_ggml_banner():
    """uma:1 marks an integrated GPU - the flag the discrete-first choice
    depends on."""
    devices = [
        runtime.VulkanDevice(int(m.group(1)), m.group(2), m.group(3) == "1")
        for m in runtime._DEVICE_RE.finditer(BANNER)
    ]
    assert [(d.index, d.integrated) for d in devices] == [(0, True), (1, False)]
    assert "NVIDIA" in devices[1].name


def test_best_device_prefers_discrete_over_integrated():
    """ggml defaults to device 0, which on a laptop is the iGPU. Without this
    preference the fast card sits idle."""
    assert runtime.best_device([IGPU, DGPU]) is DGPU
    assert runtime.best_device([IGPU]) is IGPU
    assert runtime.best_device([]) is None


def test_gpu_present_uses_whisper_on_the_discrete_card(monkeypatch):
    t = _make(monkeypatch, devices=[IGPU, DGPU])
    assert t.backend == "whisper"
    assert "vulkan:1" in t.device
    assert FakeServer.instances[0].device is DGPU
    assert FakeServer.instances[0].started


def test_no_gpu_falls_back_to_parakeet_for_a_supported_language(monkeypatch):
    t = _make(monkeypatch, devices=[], language="pt")
    assert (t.backend, t.device) == ("parakeet", "cpu")
    assert FakeServer.instances == []


def test_no_gpu_unsupported_language_uses_whisper_on_cpu(monkeypatch):
    """Parakeet covers 25 European languages; outside them it cannot stand in,
    and a slow correct transcription beats a fast wrong one."""
    t = _make(monkeypatch, devices=[], language="ja")
    assert t.backend == "whisper"
    assert t.device == "cpu"
    assert FakeServer.instances[0].device is None


def test_miris_never_gets_parakeet(monkeypatch):
    """allow_parakeet=False is how miris guarantees segment timestamps."""
    t = _make(monkeypatch, devices=[], language="pt", allow_parakeet=False)
    assert t.backend == "whisper"
    assert t.device == "cpu"


def test_gpu_failure_degrades_to_the_next_backend(monkeypatch):
    """A Vulkan device that enumerates but cannot actually run must not strand
    the user - the same class of failure that broken CUDA caused before."""
    import laris.stt_whispercpp as mod
    from laris import config

    class ExplodingOnGpu(FakeServer):
        def start(self):
            if self.device is not None:
                raise RuntimeError("vkCreateDevice failed")
            super().start()

    monkeypatch.setattr(runtime, "WhisperServer", ExplodingOnGpu)
    monkeypatch.setattr(runtime, "vulkan_devices", lambda: [DGPU])
    monkeypatch.setattr(config, "STT_LANGUAGE", "ja")   # skip the parakeet rung
    t = mod.WhisperCppTranscriber()

    assert (t.backend, t.device) == ("whisper", "cpu")


def test_every_backend_failing_boots_degraded_instead_of_raising(monkeypatch, capsys):
    """daemon.run constructs the backend and calls warm() unguarded, and the
    engine is packaged windowed - raising here would kill it with no window,
    no stderr and no popup."""
    import laris.stt_whispercpp as mod

    def boom(*a, **k):
        raise OSError("no binaries")

    monkeypatch.setattr(runtime, "vulkan_devices", lambda: [])
    monkeypatch.setattr(runtime, "ensure_model", boom)
    t = mod.WhisperCppTranscriber()

    assert t.backend == "unavailable"
    assert t.transcribe(np.zeros(16000, dtype=np.float32)) == ""
    assert "no usable backend" in capsys.readouterr().out


def test_warm_never_raises(monkeypatch):
    """daemon.py:141 calls warm() without a guard."""
    import laris.stt_whispercpp as mod

    class ExplodingInfer(FakeServer):
        def infer(self, wav, verbose):
            raise RuntimeError("gpu hung")

    monkeypatch.setattr(runtime, "WhisperServer", ExplodingInfer)
    t = _make(monkeypatch, devices=[DGPU])
    t.warm()   # must not raise


def test_transcribe_empty_returns_empty(monkeypatch):
    t = _make(monkeypatch, devices=[DGPU])
    assert t.transcribe(np.zeros(0, dtype=np.float32), 16000) == ""


def test_transcribe_with_vad_empty_returns_empty_list(monkeypatch):
    t = _make(monkeypatch, devices=[DGPU])
    assert t.transcribe_with_vad(np.zeros(0, dtype=np.float32), 16000) == []


def test_transcribe_with_vad_returns_segments_with_timestamps(monkeypatch):
    """miris.transcribe.transcribe_channel reads .start / .end / .text."""
    t = _make(monkeypatch, devices=[DGPU])
    segments = t.transcribe_with_vad(np.zeros(16000, dtype=np.float32))
    assert [(s.start, s.end, s.text) for s in segments] == [
        (0.0, 1.0, " ola"), (1.0, 2.0, " mundo")
    ]


def test_sample_rate_arguments_are_optional(monkeypatch):
    """miris calls transcribe(chunk) and transcribe_with_vad(audio) with one
    argument - the defaults must survive."""
    t = _make(monkeypatch, devices=[DGPU])
    assert t.transcribe(np.zeros(16000, dtype=np.float32)) == "ola mundo"
    assert len(t.transcribe_with_vad(np.zeros(16000, dtype=np.float32))) == 2


def test_wav_bytes_roundtrip():
    """The server is fed a real WAV built in memory; a malformed header would
    be silently mis-decoded rather than rejected."""
    import laris.stt_whispercpp as mod
    audio = np.linspace(-1.0, 1.0, 800, dtype=np.float32)
    with wave.open(io.BytesIO(mod._wav_bytes(audio, 16000)), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert w.getnframes() == 800


def test_describe_exit_names_the_illegal_instruction_status():
    """Regression: binaries built with GGML_NATIVE=ON died with 3221225501 on a
    CPU older than the build machine's. The bare number sent the reader looking
    at GPU drivers; the name points at the binary."""
    described = runtime.describe_exit(3221225501)
    assert "0xC000001D" or "ILLEGAL_INSTRUCTION" in described
    assert "ILLEGAL_INSTRUCTION" in described
    assert "3221225501" in described
    # an ordinary failure still reads sensibly
    assert runtime.describe_exit(1) == "exit code 1"


def test_crashed_gpu_probe_is_not_reported_as_a_missing_gpu(monkeypatch, capsys, tmp_path):
    """Regression: vulkan_devices() ignored the exit code, so a binary that
    crashed before printing produced 'no GPU found' on a machine with a working
    RTX 3050 - sending the next reader after the driver instead of the build."""
    cli = tmp_path / ("whisper-cli.exe" if __import__("os").name == "nt" else "whisper-cli")
    cli.write_text("")
    monkeypatch.setattr(runtime, "binaries_dir", lambda: tmp_path)

    class Crashed:
        returncode, stdout, stderr = 3221225501, "", ""

    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **k: Crashed())
    assert runtime.probe_vulkan_devices() == []
    out = capsys.readouterr().out
    assert "crashed" in out and "ILLEGAL_INSTRUCTION" in out
    assert "no GPU" not in out


def test_coopmat2_is_disabled_by_default_but_the_user_wins(monkeypatch):
    """The NV_coopmat2 kernels cost ~11s of first-run shader compilation and
    bought nothing measurable afterwards, so they are off by default - but the
    trade was measured on one GPU, so an explicit value has to survive."""
    monkeypatch.delenv("GGML_VK_DISABLE_COOPMAT2", raising=False)
    assert runtime.ggml_env()["GGML_VK_DISABLE_COOPMAT2"] == "1"

    monkeypatch.setenv("GGML_VK_DISABLE_COOPMAT2", "0")
    assert runtime.ggml_env()["GGML_VK_DISABLE_COOPMAT2"] == "0"


def _probe_counter(monkeypatch, devices):
    calls = []

    def fake_probe():
        calls.append(1)
        return list(devices)

    monkeypatch.setattr(runtime, "probe_vulkan_devices", fake_probe)
    return calls


def test_gpu_probe_is_cached_between_boots(monkeypatch, tmp_path):
    """The probe costs ~0.38s and a whole process launch on the boot path, for
    a hardware fact that almost never changes."""
    monkeypatch.setenv("VOXIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(runtime, "_binary_stamp", lambda: "123:456")
    calls = _probe_counter(monkeypatch, [DGPU])

    assert _REAL_VULKAN_DEVICES() == [DGPU]
    assert _REAL_VULKAN_DEVICES() == [DGPU]
    assert len(calls) == 1, "second boot must read the cache, not re-probe"
    assert (tmp_path / "gpu-probe.json").is_file()


def test_a_new_binary_invalidates_the_probe_cache(monkeypatch, tmp_path):
    """A different whisper.cpp build can enumerate differently, so the cache
    must not outlive the binary it was taken from."""
    monkeypatch.setenv("VOXIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(runtime, "_binary_stamp", lambda: "old")
    calls = _probe_counter(monkeypatch, [DGPU])
    _REAL_VULKAN_DEVICES()

    monkeypatch.setattr(runtime, "_binary_stamp", lambda: "new")
    _REAL_VULKAN_DEVICES()
    assert len(calls) == 2


def test_corrupt_probe_cache_falls_back_to_probing(monkeypatch, tmp_path):
    """A cache is never worth a boot failure - same self-healing shape as
    orb_theme.load_theme."""
    monkeypatch.setenv("VOXIS_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(runtime, "_binary_stamp", lambda: "123:456")
    (tmp_path / "gpu-probe.json").write_text("{not json", encoding="utf-8")
    calls = _probe_counter(monkeypatch, [IGPU])

    assert _REAL_VULKAN_DEVICES() == [IGPU]
    assert len(calls) == 1


def test_parakeet_path_shells_out_and_cleans_up(monkeypatch, tmp_path):
    import laris.stt_whispercpp as mod
    seen = {}

    def fake_parakeet(model, wav_path):
        seen["model"], seen["exists"] = model, wav_path.exists()
        return "  texto  "

    monkeypatch.setattr(runtime, "parakeet_transcribe", fake_parakeet)
    t = _make(monkeypatch, devices=[], language="pt")
    assert t.transcribe(np.zeros(16000, dtype=np.float32)) == "texto"
    assert seen["exists"] is True          # the file existed during the call
    assert "parakeet" in str(seen["model"])
