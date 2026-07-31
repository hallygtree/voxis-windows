"""whisper.cpp runtime plumbing: find the bundled binaries, pick a GPU, keep the
model files on disk, and run inference.

Two execution modes on purpose:

* **Whisper** runs through `whisper-server`, which keeps the model resident. A
  warm request answers in ~0.77s on a Vulkan GPU, and HTTP costs nothing
  measurable next to that.
* **Parakeet** has no server build upstream - only `parakeet-cli` - so it is
  invoked per utterance and pays model load every time. Measured at ~1.8s total
  for 16s of audio, which is fine for what is only the no-GPU fallback.

Device choice reads ggml's own enumeration rather than guessing: every ggml
binary prints its Vulkan devices on any invocation, including `--help`, and
tags each with `uma:` (unified memory = integrated GPU). Preferring `uma: 0`
picks the discrete card - without this, ggml defaults to device 0, which on a
laptop is usually the integrated GPU and leaves the fast card idle.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# ggml_vulkan: 1 = NVIDIA GeForce RTX 3050 Laptop GPU (NVIDIA) | uma: 0 | fp16: 1 | ...
_DEVICE_RE = re.compile(r"^ggml_vulkan:\s*(\d+)\s*=\s*(.+?)\s*\|\s*uma:\s*(\d)", re.M)

# Parakeet TDT v3 covers 25 European languages. Outside this set it cannot be
# the fallback and Whisper on CPU has to take the hit instead.
PARAKEET_LANGUAGES = frozenset(
    "en es fr de it pt ru pl uk ro nl hu el sv cs bg sk hr da fi lt sl lv et mt".split()
)

# Windows only: keep the console window from flashing on every subprocess.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# Windows NTSTATUS values a crashing ggml binary actually produces. The raw
# number tells you nothing; the name points straight at the cause.
_EXIT_STATUS = {
    0xC000001D: "STATUS_ILLEGAL_INSTRUCTION - the binary uses CPU instructions "
                "this machine does not have (built without GGML_CPU_ALL_VARIANTS?)",
    0xC0000005: "STATUS_ACCESS_VIOLATION",
    0xC0000135: "STATUS_DLL_NOT_FOUND - a DLL is missing next to the executable",
    0xC0000142: "STATUS_DLL_INIT_FAILED",
    0xC00000FD: "STATUS_STACK_OVERFLOW",
}


def describe_exit(code: int) -> str:
    """Exit codes from a crashed Windows process are unsigned NTSTATUS values.
    Printing 3221225501 tells a reader nothing; naming it does."""
    named = _EXIT_STATUS.get(code & 0xFFFFFFFF)
    return f"exit code {code}" + (f" = {named}" if named else "")


@dataclass(frozen=True)
class VulkanDevice:
    index: int
    name: str
    integrated: bool


@dataclass(frozen=True)
class ModelSpec:
    filename: str
    url: str
    size: int  # exact byte count, so a truncated download is detectable


WHISPER_MODEL = ModelSpec(
    filename="ggml-large-v3-turbo-q5_0.bin",
    url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
        "ggml-large-v3-turbo-q5_0.bin",
    size=574041195,
)
PARAKEET_MODEL = ModelSpec(
    filename="ggml-parakeet-tdt-0.6b-v3-q4_k.bin",
    url="https://huggingface.co/ggml-org/parakeet-GGUF/resolve/main/"
        "ggml-parakeet-tdt-0.6b-v3-q4_k.bin",
    size=415611879,
)


def binaries_dir() -> Path:
    """Where whisper-server / whisper-cli / parakeet-cli live. Frozen builds get
    them from the PyInstaller bundle; a dev checkout stages them in the same
    layout the CI artifact produces."""
    override = os.environ.get("VOXIS_WHISPERCPP_DIR")
    if override:
        return Path(override).expanduser()
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent.parent))
    return base / "whispercpp"


def models_dir() -> Path:
    return Path(
        os.environ.get("VOXIS_MODELS_DIR", "~/.config/voice-at/models")
    ).expanduser()


def state_dir() -> Path:
    return Path(
        os.environ.get("VOXIS_STATE_DIR", "~/.config/voice-at")
    ).expanduser()


def ggml_env() -> dict:
    """Environment for every ggml child process.

    GGML_VK_DISABLE_COOPMAT2: the NV_coopmat2 kernels are enormously expensive
    to compile the first time a given ggml-vulkan.dll runs on a machine -
    measured on an RTX 3050, the first inference took 14.6s with them and 3.9s
    without - while making no measurable difference afterwards (1.40/1.43/1.44s
    with, 1.42/1.36/1.39s without). ggml keeps no VkPipelineCache of its own, so
    that cost is entirely at the driver's mercy and is re-paid whenever the DLL
    changes. Disabling coopmat *entirely* is the mistake to avoid: that one
    costs 31% (1.78s vs 1.36s).

    setdefault, not assignment: a user who exports the variable wins, so the
    trade can be re-tested on other hardware without rebuilding.
    """
    env = dict(os.environ)
    env.setdefault("GGML_VK_DISABLE_COOPMAT2", "1")
    return env


def _exe(name: str) -> Path:
    return binaries_dir() / (name + (".exe" if os.name == "nt" else ""))


def cpu_threads() -> int:
    """ggml defaults to min(4, ncores). On a 16-thread machine that cost 2.2x
    (28.4s vs 13.0s), so the count must be passed explicitly."""
    return max(1, os.cpu_count() or 4)


def probe_vulkan_devices() -> list[VulkanDevice]:
    """Enumerate Vulkan devices by asking a ggml binary. Returns [] when there
    is no Vulkan loader, no driver, or no binary - all of which mean 'no GPU'
    and must not raise."""
    cli = _exe("whisper-cli")
    if not cli.exists():
        return []
    try:
        proc = subprocess.run(
            [str(cli), "--help"], capture_output=True, text=True, errors="replace",
            timeout=60, creationflags=_NO_WINDOW, env=ggml_env(),
        )
    except Exception as exc:  # noqa: BLE001 - probing must never kill the daemon
        print(f"[STT] Vulkan probe failed ({exc}); assuming no GPU")
        return []
    blob = (proc.stdout or "") + (proc.stderr or "")
    devices = [
        VulkanDevice(index=int(m.group(1)), name=m.group(2), integrated=m.group(3) == "1")
        for m in _DEVICE_RE.finditer(blob)
    ]
    # A crashed probe returns no devices, which is indistinguishable from a
    # machine that genuinely has none - and reporting "no GPU" for a machine
    # with a working card sends whoever reads the log after the driver instead
    # of the binary. Say which one it was.
    if not devices and proc.returncode != 0:
        print(f"[STT] the GPU probe crashed ({describe_exit(proc.returncode)}); "
              "this is a broken whisper.cpp binary, not a missing GPU")
    return devices


def _binary_stamp() -> str:
    """Identity of the binary the cache was built from. A new whisper.cpp build
    can enumerate differently, so the cache must not outlive it."""
    try:
        st = _exe("whisper-cli").stat()
        return f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return ""


def vulkan_devices() -> list[VulkanDevice]:
    """Cached device list. The probe costs ~0.38s and a whole process launch to
    discover a hardware fact that almost never changes, and it sits on the boot
    critical path. Cache invalidates when the binary changes.

    Every failure path here falls through to a live probe: a cache is not worth
    a boot failure."""
    cache = state_dir() / "gpu-probe.json"
    stamp = _binary_stamp()
    try:
        blob = json.loads(cache.read_text(encoding="utf-8"))
        if blob.get("binary") == stamp and stamp:
            return [VulkanDevice(**d) for d in blob["devices"]]
    except Exception:  # noqa: BLE001 - missing/corrupt/stale all mean "re-probe"
        pass

    devices = probe_vulkan_devices()
    try:
        _write_atomic(cache, json.dumps({
            "binary": stamp,
            "devices": [d.__dict__ for d in devices],
        }))
    except OSError as exc:
        print(f"[STT] could not cache the GPU probe ({exc}); re-probing every boot")
    return devices


def _write_atomic(path: Path, text: str) -> None:
    """Same mkstemp + os.replace shape as orb_theme._write_atomic and
    peer_discovery.write_peer - a half-written cache must never be readable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


def best_device(devices: list[VulkanDevice]) -> VulkanDevice | None:
    """Discrete GPU first, integrated second, None when there is nothing."""
    if not devices:
        return None
    for dev in devices:
        if not dev.integrated:
            return dev
    return devices[0]


def ensure_model(spec: ModelSpec, on_status=None) -> Path:
    """Download the model on first use. Only the model for the backend actually
    chosen is fetched - a GPU machine never downloads Parakeet and vice versa.

    on_status: optional callback receiving human-readable progress for the
    tray. Reports are deliberately coarse - see below."""
    path = models_dir() / spec.filename
    if path.exists() and path.stat().st_size == spec.size:
        return path
    if path.exists():
        print(f"[STT] {spec.filename} is truncated ({path.stat().st_size} of "
              f"{spec.size} bytes); re-downloading")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    total_mb = spec.size / 1048576
    print(f"[STT] downloading {spec.filename} ({total_mb:.0f} MB)...")
    if on_status is not None:
        on_status(f"baixando modelo 0% de {total_mb:.0f} MB")
    downloaded = 0
    last_pct, last_report = -1, 0.0
    with urllib.request.urlopen(spec.url, timeout=60) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            downloaded += len(chunk)
            if on_status is None:
                continue
            pct = min(100, downloaded * 100 // max(1, spec.size))
            now = time.monotonic()
            # At most one report per percent AND per second: every change
            # rebuilds the tray menu on its main thread, so a finer-grained
            # counter would spend more effort repainting than downloading.
            if pct != last_pct and now - last_report >= 1.0:
                last_pct, last_report = pct, now
                on_status(f"baixando modelo {pct}% de {total_mb:.0f} MB")
    got = tmp.stat().st_size
    if got != spec.size:
        tmp.unlink(missing_ok=True)
        raise OSError(f"{spec.filename}: expected {spec.size} bytes, got {got}")
    tmp.replace(path)
    print(f"[STT] {spec.filename} ready")
    return path


def resolve_whisper_model(name: str, on_status=None) -> Path:
    """Honour config.STT_MODEL_GGML. The default name downloads on demand;
    anything else has to exist already (in the models dir or as a path),
    because there is no download URL for an arbitrary ggml file."""
    name = (name or "").strip()
    if not name or name == WHISPER_MODEL.filename:
        return ensure_model(WHISPER_MODEL, on_status)
    for candidate in (models_dir() / name, Path(name).expanduser()):
        if candidate.is_file():
            return candidate
    print(f"[STT] {name} not found in {models_dir()}; "
          f"falling back to {WHISPER_MODEL.filename}")
    return ensure_model(WHISPER_MODEL, on_status)


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class WhisperServer:
    """Persistent whisper-server process. Owns its port and lifetime."""

    def __init__(self, model: Path, device: VulkanDevice | None, language: str) -> None:
        self.model = model
        self.device = device
        self.language = language
        self.port = _free_port()
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        cmd = [
            str(_exe("whisper-server")),
            "-m", str(self.model),
            "--host", "127.0.0.1",
            "--port", str(self.port),
            "-t", str(cpu_threads()),
            "-l", self.language or "auto",
        ]
        if self.device is not None:
            cmd += ["-dev", str(self.device.index)]
        else:
            cmd += ["-ng"]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW, env=ggml_env(),
        )
        # A leaked server holds the model in VRAM for the life of the session.
        # The daemon does not always get to shut down cleanly (the tray kills
        # it), so registering here rather than relying on callers.
        atexit.register(self.stop)
        self._wait_until_listening()

    def _wait_until_listening(self, timeout: float = 120.0) -> None:
        """The first ever launch compiles Vulkan pipelines (~25s measured);
        the driver caches them, so later launches answer in under a second."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(
                    f"whisper-server exited: {describe_exit(self._proc.returncode)}"
                )
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/", timeout=2)
                return
            except urllib.error.HTTPError:
                return           # any HTTP status means the socket is serving
            except Exception:    # noqa: BLE001 - not up yet
                time.sleep(0.25)
        raise TimeoutError("whisper-server did not start listening")

    def infer(self, wav: bytes, verbose: bool) -> dict:
        fmt = "verbose_json" if verbose else "json"
        body, content_type = _multipart(
            {"response_format": fmt}, "file", "audio.wav", wav
        )
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/inference", data=body, method="POST",
            headers={"Content-Type": content_type},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def stop(self) -> None:
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None


def parakeet_transcribe(model: Path, wav_path: Path) -> str:
    """One-shot CLI call. Parakeet has no server build upstream, and its total
    cost including model load is ~1.8s, so per-utterance loading is tolerable
    for a fallback."""
    proc = subprocess.run(
        [str(_exe("parakeet-cli")), "-m", str(model), "-f", str(wav_path),
         "-ng", "-t", str(cpu_threads()), "-np"],
        capture_output=True, text=True, errors="replace", timeout=600,
        creationflags=_NO_WINDOW, env=ggml_env(),
    )
    if proc.returncode != 0:
        # Lead with the decoded status: ggml prints its device banner to stderr
        # on every run, so a raw tail buries the actual failure under a wall of
        # unrelated hardware detail.
        raise RuntimeError(f"parakeet-cli failed: {describe_exit(proc.returncode)}"
                           f" | stderr tail: {(proc.stderr or '').strip()[-200:]}")
    return (proc.stdout or "").strip()


def _multipart(fields: dict[str, str], file_field: str, filename: str,
               payload: bytes) -> tuple[bytes, str]:
    """Minimal multipart/form-data. urllib has no helper and the project has no
    `requests` dependency (peer_client.py is urllib too), so build it here
    rather than add one."""
    boundary = "----voxis" + os.urandom(8).hex()
    out = bytearray()
    for key, value in fields.items():
        out += (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n").encode()
    out += (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\n'
            f"Content-Type: audio/wav\r\n\r\n").encode()
    out += payload
    out += f"\r\n--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"
