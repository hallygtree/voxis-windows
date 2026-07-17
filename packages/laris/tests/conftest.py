"""Suite-wide fixtures for laris (none needed yet)."""
import os

# Tests must never read the developer's real laris-settings.json - laris.config
# resolves overrides at import time, so this has to run before any laris import.
os.environ["LARIS_SETTINGS_PATH"] = "/nonexistent/laris-settings.json"
