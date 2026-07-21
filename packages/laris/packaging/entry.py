"""PyInstaller entrypoint for the frozen laris engine. Equivalent to
`python -m laris`: boots the overlay server and runs the PTT voice loop."""
import sys

# The frozen engine is windowed and the tray redirects its stdout/stderr to
# laris-engine.log - the only diagnostics a remote tester can send. Redirected
# to a file, stdout is block-buffered, so a *running* engine wrote nothing to
# that log until it died (observed: the boot banner landed after the crash
# traceback, out of order). Line-buffer both streams so the log is useful while
# the process is still alive. sys.stdout is None when the windowed exe runs
# with no redirection at all, hence the guard.
for _stream in (sys.stdout, sys.stderr):
    if _stream is not None:
        try:
            _stream.reconfigure(line_buffering=True)
        except (AttributeError, OSError):  # not a TextIOWrapper / not reconfigurable
            pass

from laris.__main__ import main  # noqa: E402 - must follow the buffering setup

if __name__ == "__main__":
    main()
