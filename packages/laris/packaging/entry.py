"""PyInstaller entrypoint for the frozen laris engine. Equivalent to
`python -m laris`: boots the overlay server and runs the PTT voice loop."""
from laris.__main__ import main

if __name__ == "__main__":
    main()
