"""Config: ~/.miris/config.toml - categories -> vault folders, llm command, paths."""
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Shutdown contract between `miris stop` and the detached recorder: the CLI
# creates <session>/stop, the recorder polls for it and exits gracefully.
# Windows has no deliverable SIGTERM (os.kill is TerminateProcess), so a file
# both processes agree on is the only portable stop channel. Lives in config
# so the CLI does not have to import the recorder (numpy/sounddevice) just to
# learn the filename.
STOP_SENTINEL = "stop"

DEFAULT_TOML = """\
vault_root = "~/vault"
inbox = "inbox"
# swapping provider = edit this line, never code (Google killed gemini-cli logins mid-2026)
llm_command = ["agy", "--model", "Gemini 3.5 Flash (Medium)", "-p"]

[categories]
# category -> vault-relative folder; edit to taste
trabalho = "work/meetings"
minhas-empresas = "own/meetings"
entrevistas = "interviews"
"""


def miris_home() -> Path:
    """MIRIS state dir (~/.miris unless MIRIS_HOME overrides), read at call time."""
    return Path(os.environ.get("MIRIS_HOME", "~/.miris")).expanduser()


@dataclass(frozen=True)
class Config:
    vault_root: Path
    inbox: str
    llm_command: list[str]
    categories: dict[str, str]
    sessions_dir: Path


def load(path: Path | None = None) -> Config:
    """Load config; the default location is auto-created with DEFAULT_TOML,
    an explicit path must already exist."""
    home = miris_home()
    if path is None:
        path = home / "config.toml"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(DEFAULT_TOML, encoding="utf-8")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return Config(
        vault_root=Path(data["vault_root"]).expanduser(),
        inbox=data.get("inbox", "inbox"),
        llm_command=list(data["llm_command"]),
        categories=dict(data.get("categories", {})),
        sessions_dir=home / "sessions",
    )
