"""Windows dictation output - clipboard + Ctrl+V, with the OS seams mocked."""
import laris.dictation_windows as dw


def test_format_for_focus_prose_default():
    assert dw.format_for_focus("hello world") == "Hello world."
    assert dw.format_for_focus("já tem ponto.") == "Já tem ponto."
    assert dw.format_for_focus("") == ""


def test_type_text_copies_pastes_and_restores(monkeypatch):
    events = []
    monkeypatch.setattr(dw, "_get_clipboard", lambda: "OLD")
    monkeypatch.setattr(dw, "_set_clipboard", lambda t: events.append(("copy", t)))
    monkeypatch.setattr(dw, "_paste_ctrl_v", lambda: events.append(("paste", None)))
    monkeypatch.setattr(dw.time, "sleep", lambda _s: None)

    dw.type_text("olá mundo")

    assert events == [
        ("copy", "Olá mundo."),
        ("paste", None),
        ("copy", "OLD"),
    ]


def test_type_text_survives_clipboard_read_failure(monkeypatch):
    events = []

    def boom():
        raise RuntimeError("no clipboard")

    monkeypatch.setattr(dw, "_get_clipboard", boom)
    monkeypatch.setattr(dw, "_set_clipboard", lambda t: events.append(("copy", t)))
    monkeypatch.setattr(dw, "_paste_ctrl_v", lambda: events.append(("paste", None)))
    monkeypatch.setattr(dw.time, "sleep", lambda _s: None)

    dw.type_text("teste")

    assert events == [("copy", "Teste."), ("paste", None)]
