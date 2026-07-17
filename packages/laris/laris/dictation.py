"""Dictation output into the currently focused macOS app."""
import subprocess
import time

# A pending TCC permission prompt (Automation/Accessibility) makes osascript
# hang forever; without a timeout that freezes the whole single-threaded
# voice loop - both PTT keys go dead silently. Same mitigation as the
# reference implementation (~/code/random/macos/actions.py).
_SUBPROCESS_TIMEOUT_SECONDS = 4
_PASTE_SETTLE_SECONDS = 0.3


def _paste_via_keyboard() -> None:
    """Send Cmd+V from THIS process as a single flagged CGEvent.

    Not osascript: under a launchd agent, osascript is a child process whose
    own TCC identity needs Accessibility, and macOS refuses it with error
    1002 no matter what the panes show.

    Not pynput Controller either: posting separate cmd-down/cmd-up modifier
    events desyncs when the user's physical PTT key IS right-Command - a
    lost synthetic cmd-up leaves the system with Cmd stuck held forever
    (observed live: every subsequent keypress acted as Cmd+key). Setting the
    Command flag ON the V key event itself means no synthetic modifier
    events exist at all - nothing can get stuck."""
    import Quartz

    KVK_ANSI_V = 9
    v_down = Quartz.CGEventCreateKeyboardEvent(None, KVK_ANSI_V, True)
    v_up = Quartz.CGEventCreateKeyboardEvent(None, KVK_ANSI_V, False)
    Quartz.CGEventSetFlags(v_down, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventSetFlags(v_up, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, v_down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, v_up)


def type_text(text: str) -> None:
    """Paste text into the focused app via clipboard + Cmd+V.

    Clipboard-paste is the standard mechanism for local dictation tools:
    fast for long text and unicode-safe, where System Events keystroke of
    arbitrary strings is slow and fragile. Best-effort restore of the
    previous clipboard afterwards.
    """
    from laris.app_context import format_for_focus
    text = format_for_focus(text)

    previous_clipboard: bytes | None = None
    try:
        previous = subprocess.run(
            ["pbpaste"], capture_output=True, timeout=_SUBPROCESS_TIMEOUT_SECONDS
        )
        if previous.returncode == 0:
            previous_clipboard = previous.stdout
    except Exception:  # noqa: BLE001 - restore is best-effort; paste must still happen
        previous_clipboard = None

    try:
        copied = subprocess.run(
            ["pbcopy"], input=text.encode(), timeout=_SUBPROCESS_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        print("[Dictation] pbcopy timed out - macOS permission prompt pending?")
        return
    if copied.returncode != 0:
        print(f"[Dictation] pbcopy failed (rc={copied.returncode})")
        return

    try:
        _paste_via_keyboard()
    except Exception as exc:  # noqa: BLE001 - paste failure must not kill the voice loop
        # leave the dictated text on the clipboard so the user can Cmd+V manually
        print(
            f"[Dictation] paste keystroke failed: {exc!r} - check the Accessibility "
            "grant for Python.app; the dictated text stays on the clipboard"
        )
        return

    # ponytail: fixed settle delay - a slow frontmost app could read the
    # pasteboard only after the restore below and paste the OLD clipboard;
    # poll NSPasteboard changeCount instead if this ever bites in practice
    time.sleep(_PASTE_SETTLE_SECONDS)

    if previous_clipboard is not None:
        try:
            subprocess.run(
                ["pbcopy"], input=previous_clipboard, timeout=_SUBPROCESS_TIMEOUT_SECONDS
            )
        except Exception:  # noqa: BLE001 - restore is best-effort
            pass
