"""Dictation output on Windows: clipboard + Ctrl+V. pyperclip/pynput are
imported lazily inside the seams so importing this module never loads them
(and unit tests can patch the seams without a real desktop). The PTT key on
Windows defaults to right-shift, not Ctrl, so a Ctrl+V paste never collides
with the held hotkey."""
from __future__ import annotations

import time

_PASTE_SETTLE_SECONDS = 0.3
_TERMINAL = (".", "!", "?", ":")


def format_for_focus(text: str) -> str:
    """Default prose formatting (no app detection on Windows v1): capitalize
    the first letter and add a period if the text has no terminal punctuation
    and is a single line."""
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if not text.endswith(_TERMINAL) and "\n" not in text:
        text += "."
    return text


def _get_clipboard() -> str:
    import pyperclip
    return pyperclip.paste()


def _set_clipboard(text: str) -> None:
    import pyperclip
    pyperclip.copy(text)


def _paste_ctrl_v() -> None:
    from pynput.keyboard import Controller, Key
    kb = Controller()
    with kb.pressed(Key.ctrl):
        kb.press("v")
        kb.release("v")


def type_text(text: str) -> None:
    """Paste text into the focused app via clipboard + Ctrl+V, restoring the
    previous clipboard best-effort."""
    text = format_for_focus(text)

    previous: str | None = None
    try:
        previous = _get_clipboard()
    except Exception:  # noqa: BLE001 - restore is best-effort; paste must still happen
        previous = None

    try:
        _set_clipboard(text)
        _paste_ctrl_v()
    except Exception as exc:  # noqa: BLE001 - paste failure must not kill the voice loop
        print(f"[Dictation] paste failed: {exc!r} - text left on the clipboard")
        return

    time.sleep(_PASTE_SETTLE_SECONDS)

    if previous is not None:
        try:
            _set_clipboard(previous)
        except Exception:  # noqa: BLE001 - restore is best-effort
            pass
