"""PyInstaller entrypoint for the frozen miris-engine.
Dispatches subcommands: start | stop | status | retry <session> | doctor | __recorder <session>"""
import sys

if __name__ == "__main__":
    # When frozen, sys.argv[0] is the exe name; sys.argv[1:] are the actual arguments
    if len(sys.argv) > 1 and sys.argv[1] == "__recorder":
        # Internal subcommand: start recording directly
        # Called as: miris-engine __recorder <session_dir>
        if len(sys.argv) < 3:
            sys.exit("usage: miris-engine __recorder <session_dir>")
        session_dir = sys.argv[2]
        from miris.recorder import main
        # Fake sys.argv for recorder.main() to parse
        sys.argv = ["miris", session_dir]
        main()
    else:
        # CLI subcommands: start | stop | status | retry | doctor
        from miris.cli import main
        main()
