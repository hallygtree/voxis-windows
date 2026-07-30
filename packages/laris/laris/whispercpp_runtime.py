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


def _exe(name: str) -> Path:
    return binaries_dir() / (name + (".exe" if os.name == "nt" else ""))


def cpu_threads() -> int:
    """ggml defaults to min(4, ncores). On a 16-thread machine that cost 2.2x
    (28.4s vs 13.0s), so the count must be passed explicitly."""
    return max(1, os.cpu_count() or 4)


def vulkan_devices() -> list[VulkanDevice]:
    """Enumerate Vulkan devices by asking a ggml binary. Returns [] when there
    is no Vulkan loader, no driver, or no binary - all of which mean 'no GPU'
    and must not raise."""
    cli = _exe("whisper-cli")
    if not cli.exists():
        return []
    try:
        proc = subprocess.run(
            [str(cli), "--help"], capture_output=True, text=True, errors="replace",
            timeout=60, creationflags=_NO_WINDOW,
        )
    except Exception as exc:  # noqa: BLE001 - probing must never kill the daemon
        print(f"[STT] Vulkan probe failed ({exc}); assuming no GPU")
        return []
    blob = (proc.stdout or "") + (proc.stderr or "")
    return [
        VulkanDevice(index=int(m.group(1)), name=m.group(2), integrated=m.group(3) == "1")
        for m in _DEVICE_RE.finditer(blob)
    ]


def best_device(devices: list[VulkanDevice]) -> VulkanDevice | None:
    """Discrete GPU first, integrated second, None when there is nothing."""
    if not devices:
        return None
    for dev in devices:
        if not dev.integrated:
            return dev
    return devices[0]


def ensure_model(spec: ModelSpec) -> Path:
    """Download the model on first use. Only the model for the backend actually
    chosen is fetched - a GPU machine never downloads Parakeet and vice versa."""
    path = models_dir() / spec.filename
    if path.exists() and path.stat().st_size == spec.size:
        return path
    if path.exists():
        print(f"[STT] {spec.filename} is truncated ({path.stat().st_size} of "
              f"{spec.size} bytes); re-downloading")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    print(f"[STT] downloading {spec.filename} ({spec.size / 1048576:.0f} MB)...")
    with urllib.request.urlopen(spec.url, timeout=60) as resp, open(tmp, "wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    got = tmp.stat().st_size
    if got != spec.size:
        tmp.unlink(missing_ok=True)
        raise OSError(f"{spec.filename}: expected {spec.size} bytes, got {got}")
    tmp.replace(path)
    print(f"[STT] {spec.filename} ready")
    return path


def resolve_whisper_model(name: str) -> Path:
    """Honour config.STT_MODEL_GGML. The default name downloads on demand;
    anything else has to exist already (in the models dir or as a path),
    because there is no download URL for an arbitrary ggml file."""
    name = (name or "").strip()
    if not name or name == WHISPER_MODEL.filename:
        return ensure_model(WHISPER_MODEL)
    for candidate in (models_dir() / name, Path(name).expanduser()):
        if candidate.is_file():
            return candidate
    print(f"[STT] {name} not found in {models_dir()}; "
          f"falling back to {WHISPER_MODEL.filename}")
    return ensure_model(WHISPER_MODEL)


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
            creationflags=_NO_WINDOW,
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
                    f"whisper-server exited with code {self._proc.returncode}"
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
        creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"parakeet-cli failed ({proc.returncode}): "
                           f"{(proc.stderr or '')[-300:]}")
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
