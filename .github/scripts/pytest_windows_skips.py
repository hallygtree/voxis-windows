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
    "evdev", "gi", "faster_whisper", "ctranslate2",     # Linux
}


# Upstream tests whose fixture is POSIX itself - a `#!/bin/sh` script run as
# the LLM, /usr/bin/true - and so cannot run on Windows. The same code paths
# have Windows-runnable tests (test_notes uses a Python LLM; test_pipeline's
# test_process_session_llm_failure_goes_to_inbox). Listed by node id so a
# rename upstream makes the test fail here instead of silently vanishing.
POSIX_FIXTURE_TESTS = {
    "tests/test_cli.py::test_the_doctor_warns_that_a_bare_llm_command_is_not_found_from_the_tray",
    "tests/test_cli.py::test_the_doctor_does_not_warn_about_an_llm_command_given_by_full_path",
    "tests/test_pipeline.py::test_process_session_happy_path",
    "tests/test_pipeline.py::test_process_session_records_note_path",
    "tests/test_pipeline.py::test_process_session_reuses_cached_transcript",
    "tests/test_pipeline.py::test_empty_transcript_cache_is_rebuilt",
}

# Upstream tests that fake Linux in a child interpreter, where the plugin cannot
# see the missing faster_whisper; the in-process Linux tests are skipped by
# the import rule below.
LINUX_CHILD_TESTS = {
    "tests/test_pipeline.py::test_on_linux_meetings_reach_faster_whisper_with_language_auto_detect",
}


def pytest_collection_modifyitems(config, items):
    posix = pytest.mark.skip(reason="POSIX-only fixture (/bin/sh script or /usr/bin/true)")
    linux = pytest.mark.skip(reason="fakes Linux in a child process that needs faster_whisper")
    for item in items:
        nodeid = item.nodeid.replace("\\", "/")
        if nodeid in POSIX_FIXTURE_TESTS:
            item.add_marker(posix)
        elif nodeid in LINUX_CHILD_TESTS:
            item.add_marker(linux)


def _missing_platform_module(exc: BaseException | None) -> str | None:
    """The platform-only module whose absence caused exc, if any. Follows the
    cause chain: monkeypatch.setattr("pkg.mod.attr", ...) re-raises the
    ModuleNotFoundError as a plain ImportError."""
    while exc is not None:
        if isinstance(exc, ModuleNotFoundError):
            name = (exc.name or "").split(".")[0]
            if name in PLATFORM_ONLY:
                return name
        exc = exc.__cause__ or exc.__context__
    return None


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if call.excinfo is None or not call.excinfo.errisinstance(ImportError):
        return
    missing = _missing_platform_module(call.excinfo.value)
    if missing is not None:
        report.outcome = "skipped"
        report.longrepr = (str(item.path), item.location[1] or 0,
                           f"needs {missing}, which the Windows bundle does not ship")
