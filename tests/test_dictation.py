from types import SimpleNamespace


def test_type_text_pastes_text_and_restores_clipboard(monkeypatch):
    from laris.dictation import type_text

    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv == ["pbpaste"]:
            return SimpleNamespace(returncode=0, stdout=b"old clipboard")
        return SimpleNamespace(returncode=0, stdout=b"")

    monkeypatch.setattr("laris.dictation.subprocess.run", fake_run)
    monkeypatch.setattr("laris.dictation.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("laris.dictation._paste_via_keyboard", lambda: calls.append("PASTE"))
    # format_for_focus reads the REAL frontmost app - without this pin the
    # test's outcome depends on which window the developer has focused
    monkeypatch.setattr("laris.app_context.format_for_focus", lambda text: text)

    type_text("olá mundo")

    assert calls == [
        (["pbpaste"], {"capture_output": True, "timeout": 4}),
        (["pbcopy"], {"input": "olá mundo".encode(), "timeout": 4}),
        "PASTE",
        (["pbcopy"], {"input": b"old clipboard", "timeout": 4}),
    ]


def test_type_text_does_not_restore_clipboard_when_paste_fails(monkeypatch):
    """A failed paste leaves the dictated text on the clipboard so the user
    can Cmd+V manually - no restore."""
    from laris import dictation

    calls = []

    class FakeResult:
        def __init__(self, returncode):
            self.returncode = returncode
            self.stdout = b"old clipboard"

    def fake_run(argv, **kwargs):
        calls.append(argv[0])
        return FakeResult(0)

    def failing_paste():
        calls.append("paste")
        raise RuntimeError("no accessibility grant")

    monkeypatch.setattr(dictation.subprocess, "run", fake_run)
    monkeypatch.setattr(dictation.time, "sleep", lambda _s: None)
    monkeypatch.setattr(dictation, "_paste_via_keyboard", failing_paste)

    dictation.type_text("hello")

    assert calls == ["pbpaste", "pbcopy", "paste"]  # no trailing restore pbcopy
