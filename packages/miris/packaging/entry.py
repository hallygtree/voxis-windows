"""PyInstaller entrypoint for the frozen miris-engine.

The CLI spawns its children as `<python> -m miris.recorder <session>` and
`<python> -m miris.pipeline <session>`, and both the CLI and the tray find a
live child by those words in its command line. Frozen, <python> is this
executable, so it accepts the same `-m <module>` form and the command line
reads the same. Anything else is a CLI subcommand (start, stop, status, ...).
"""
import runpy
import sys

_CHILDREN = ("miris.recorder", "miris.pipeline")

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "-m" and sys.argv[2] in _CHILDREN:
        module = sys.argv[2]
        sys.argv = [sys.argv[0], *sys.argv[3:]]  # what `python -m` hands the module
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    else:
        from miris.cli import main
        main()
