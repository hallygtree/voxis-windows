"""Floating dictation indicator, run as a child process:
`python -m laris.overlay_app` with OVERLAY_URL set.

A transparent non-activating panel hosting a WKWebView that loads the
dashboard's own orb page (/overlay) - identical visuals, same
/ws/voice subscription. Stdin only controls window visibility
("show ..." / "hide"); phases and captions arrive over the websocket.
Exits when stdin closes (daemon died).

Window work only - needs no TCC permission.
"""
from __future__ import annotations

import os
import sys
import threading

_SIZE = 120.0
_TOP_MARGIN = 40.0
_LEFT_MARGIN = 16.0


def main() -> None:
    import AppKit
    import WebKit

    url = os.environ.get("OVERLAY_URL", "")
    if not url:
        print("OVERLAY_URL not set", file=sys.stderr)
        sys.exit(1)

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    screen = AppKit.NSScreen.mainScreen().frame()
    # top-left corner: x from left margin, y from top (macOS origin = bottom-left)
    rect = AppKit.NSMakeRect(
        _LEFT_MARGIN,
        screen.size.height - _SIZE - _TOP_MARGIN,
        _SIZE, _SIZE
    )

    panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        rect,
        AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
        AppKit.NSBackingStoreBuffered,
        False,
    )
    panel.setLevel_(AppKit.NSStatusWindowLevel)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(AppKit.NSColor.clearColor())
    panel.setHasShadow_(False)
    panel.setIgnoresMouseEvents_(True)
    panel.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
    )

    config = WebKit.WKWebViewConfiguration.alloc().init()
    web = WebKit.WKWebView.alloc().initWithFrame_configuration_(
        AppKit.NSMakeRect(0, 0, _SIZE, _SIZE), config
    )
    try:
        # KVC switch WebKit ships but doesn't expose as API; without it the
        # webview paints a white page background behind the orb
        web.setValue_forKey_(False, "drawsBackground")
    except Exception:  # noqa: BLE001 - fall back to underPageBackgroundColor only
        pass
    try:
        web.setUnderPageBackgroundColor_(AppKit.NSColor.clearColor())
    except Exception:  # noqa: BLE001 - older macOS without the setter
        pass
    try:
        web.setBackgroundColor_(AppKit.NSColor.clearColor())
    except Exception:  # noqa: BLE001
        pass
    try:
        web.setOpaque_(False)
    except Exception:  # noqa: BLE001
        pass
    panel.setContentView_(web)

    # bypass the webview cache: stale voice-orb.js kept an old opaque-canvas
    # bug alive through two fix attempts during live debugging
    request = AppKit.NSURLRequest.requestWithURL_cachePolicy_timeoutInterval_(
        AppKit.NSURL.URLWithString_(url),
        AppKit.NSURLRequestReloadIgnoringLocalCacheData,
        15.0,
    )
    web.loadRequest_(request)

    def apply(command: str) -> None:
        if command.startswith("show"):
            panel.orderFrontRegardless()
        elif command == "hide":
            panel.orderOut_(None)

    def read_stdin() -> None:
        for raw in sys.stdin:
            command = raw.strip()
            if not command:
                continue
            AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
                lambda cmd=command: apply(cmd)
            )
        # daemon closed the pipe: leave with it
        AppKit.NSOperationQueue.mainQueue().addOperationWithBlock_(
            lambda: app.terminate_(None)
        )

    threading.Thread(target=read_stdin, daemon=True).start()
    app.run()


if __name__ == "__main__":
    main()
