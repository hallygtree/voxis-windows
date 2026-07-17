from laris.phrase_matching import is_send_confirmation, match_wake_phrase


def test_match_wake_phrase_detects_variants():
    assert match_wake_phrase("Ola kiris, oi tudo bem") is True
    assert match_wake_phrase("ola, kiris quero abrir a lina") is True
    assert match_wake_phrase("oi kiris") is True


def test_match_wake_phrase_rejects_unrelated_text():
    assert match_wake_phrase("que horas sao") is False


def test_match_wake_phrase_ignores_accents_and_punctuation():
    assert match_wake_phrase("Olá, kiris!!") is True


def test_match_wake_phrase_covers_observed_mistranscriptions():
    # Real mlx-whisper output for "ola kiris" during live testing (2026-07-07).
    assert match_wake_phrase("Olá, Kitties.") is True
    assert match_wake_phrase("Olá, Kyrus.") is True
    assert match_wake_phrase("Olá Curios.") is True
    assert match_wake_phrase("Olá, Curies.") is True


def test_is_send_confirmation_matches_known_phrases():
    assert is_send_confirmation("manda") is True
    assert is_send_confirmation("Pode mandar!") is True
    assert is_send_confirmation("enter") is True


def test_is_send_confirmation_rejects_other_text():
    assert is_send_confirmation("cria um arquivo novo") is False


def test_match_close_phrase_extracts_target():
    from laris.phrase_matching import match_close_phrase

    assert match_close_phrase("Fechar lina") == "lina"
    assert match_close_phrase("fecha o axon") == "axon"
    assert match_close_phrase("encerrar a lume") == "lume"


def test_match_close_phrase_returns_none_otherwise():
    from laris.phrase_matching import match_close_phrase

    assert match_close_phrase("lina") is None
    assert match_close_phrase("fechar") is None  # verb alone, no target


def test_match_open_phrase_extracts_target():
    from laris.phrase_matching import match_open_phrase

    assert match_open_phrase("Abrir lina") == "lina"
    assert match_open_phrase("abre o axon") == "axon"


def test_match_open_phrase_returns_none_otherwise():
    from laris.phrase_matching import match_open_phrase

    assert match_open_phrase("lina") is None
    assert match_open_phrase("abrir") is None



