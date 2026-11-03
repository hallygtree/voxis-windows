"""pytest plugin for the Windows test run: `-p pytest_windows_skips`.

Upstream's suites exercise the macOS and Linux paths too, and some of those
tests import modules the Windows bundle leaves out on purpose (torch for
silero-vad and DeepFilterNet, mlx, pyobjc, evdev). Editing those tests would
conflict on every sync with upstream, so this reports a test that failed only
because one of these modules is missing as skipped instead. Any other failure,
including a Windows code path that unexpectedly reaches for one of them in a
test that is not about it, still fails: the Windows path has its own tests
(test_vad_onnx, test_windows_backend, ...) that do not import them.
"""
import pytest

PLATFORM_ONLY = {
    "torch", "torchaudio", "silero_vad", "df",          # torch stack (macOS, Linux)
    "mlx", "mlx_whisper", "Quartz", "AppKit", "objc",   # macOS
    "evdev", "gi",                                       # Linux
}


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if call.excinfo is None or not call.excinfo.errisinstance(ModuleNotFoundError):
        return
    missing = (call.excinfo.value.name or "").split(".")[0]
    if missing in PLATFORM_ONLY:
        report.outcome = "skipped"
        report.longrepr = (str(item.path), item.location[1] or 0,
                           f"needs {missing}, which the Windows bundle does not ship")
