"""Wake-phrase and send-confirmation matching - pure string logic, no ML,
no I/O. Intentionally simple prefix/membership matching (not a trained
wake-word model) - see design spec's documented wake-word ceiling."""
import re
import unicodedata

WAKE_PHRASES = [
    "ola kiris",
    "ola, kiris",
    "oi kiris",
    "e kiris",
    # ponytail: "kiris" isn't a real pt-BR word, so mlx-whisper mishears it
    # inconsistently - these are the actual mistranscriptions observed
    # during live testing (2026-07-07), not guessed variants. Add more
    # here if new mishearings show up; if the list keeps growing, that's
    # the signal to pick a wake word Whisper's pt-BR model handles more
    # reliably instead of chasing its error modes forever.
    "ola kitties",
    "ola kyrus",
    "ola curios",
    "ola curies",
]

SEND_PHRASES = {
    "enter",
    "manda",
    "manda ai",
    "pode mandar",
    "envia",
}

CLOSE_VERBS = ("fechar", "encerrar", "fecha", "encerra")
OPEN_VERBS = ("abrir", "abre")


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[.,!?;:]+", "", text)
    text = re.sub(r"\s+", " ", text)
    text = "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )
    return text.strip()


def match_wake_phrase(text: str) -> bool:
    """True if the utterance starts with a wake-phrase variant."""
    normalized = _normalize(text)
    return any(normalized.startswith(_normalize(phrase)) for phrase in WAKE_PHRASES)


def is_send_confirmation(text: str) -> bool:
    """True if the utterance is (only) a send-confirmation phrase."""
    return _normalize(text) in SEND_PHRASES


def _match_verb_phrase(text: str, verbs: tuple[str, ...]) -> str | None:
    """Return the target of a "<verb> <projeto>" utterance, or None.
    Strips a leading article so "fecha o axon" targets "axon"."""
    normalized = _normalize(text)
    for verb in verbs:
        if normalized.startswith(verb + " "):
            target = normalized[len(verb):].strip()
            return re.sub(r"^[oa] ", "", target) or None
    return None


def match_close_phrase(text: str) -> str | None:
    return _match_verb_phrase(text, CLOSE_VERBS)


def match_open_phrase(text: str) -> str | None:
    return _match_verb_phrase(text, OPEN_VERBS)



