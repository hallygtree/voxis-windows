"""The Windows hooks in upstream's shared miris modules: each test pins one
branch that only the Windows bundle takes."""
import subprocess
import sys
from pathlib import Path

import numpy as np


def test_meetings_on_windows_use_whisper_without_the_parakeet_fallback(monkeypatch):
    from miris import pipeline

    built = {}

    class FakeWindowsBackend:
        def __init__(self, allow_parakeet=True):
            built["allow_parakeet"] = allow_parakeet

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("laris.platform.windows.WindowsBackend", FakeWindowsBackend)

    transcriber = pipeline._default_transcriber_factory()

    assert built == {"allow_parakeet": False}
    assert isinstance(transcriber._backend, FakeWindowsBackend)


def test_speech_spans_fall_back_to_onnx_without_torch(monkeypatch):
    import builtins

    from miris import transcribe

    real_import = builtins.__import__

    def no_torch(name, *args, **kwargs):
        if name.split(".")[0] in {"torch", "silero_vad"}:
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    seen = {}

    def fake_onnx_spans(audio, sr):
        seen["call"] = (len(audio), sr)
        return [(0, 160)]

    monkeypatch.setattr(builtins, "__import__", no_torch)
    monkeypatch.setattr("laris.vad_onnx.speech_spans", fake_onnx_spans)

    assert transcribe.speech_spans(np.zeros(1600, dtype=np.float32)) == [(0, 160)]
    assert seen == {"call": (1600, 16000)}


def test_a_windows_command_line_matches_its_session(monkeypatch):
    """psutil hands back a list; it is quoted the Windows way and split back
    without eating the backslashes of the session path."""
    from miris import session

    monkeypatch.setattr(sys, "platform", "win32")
    session_dir = Path(r"C:\Users\a b\.local\share\miris\sessions\20260716-1000")
    command = subprocess.list2cmdline(
        [r"C:\Program Files\VOXIS\miris-engine.exe", "-m", "miris.recorder", str(session_dir)])

    assert session.process_matches(42, "miris.recorder", session_dir, lambda pid: command)
    assert not session.process_matches(42, "miris.pipeline", session_dir, lambda pid: command)
    assert not session.process_matches(42, "miris.recorder", Path(r"C:\other"), lambda pid: command)


def test_the_frozen_entry_runs_children_from_the_same_command_line(monkeypatch, tmp_path):
    """The CLI spawns `<exe> -m miris.recorder <session>`; frozen, <exe> is
    miris-engine, which must run that module with the session as argv[1]."""
    import runpy

    entry = Path(__file__).resolve().parent.parent / "packaging" / "entry.py"
    ran = {}

    def fake_run_module(module, run_name, alter_sys):
        ran["module"], ran["argv"] = module, list(sys.argv)

    monkeypatch.setattr(runpy, "run_module", fake_run_module)
    monkeypatch.setattr(sys, "argv", ["miris-engine.exe", "-m", "miris.recorder", str(tmp_path)])

    runpy.run_path(str(entry), run_name="__main__")

    # argv[0] is whatever launched it (run_path puts entry.py there); the
    # module reads the session from argv[1], as under `python -m`
    assert ran["module"] == "miris.recorder"
    assert ran["argv"][1:] == [str(tmp_path)]
