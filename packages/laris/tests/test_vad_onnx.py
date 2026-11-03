"""The utterance state machine, driven by scripted probabilities.

This is the part that decides when a sentence starts and stops, and until now
nothing tested it on the Windows profile: the two existing VAD tests are
@requires_torch and both bypass __init__, so on a torch-free machine zero lines
of the generator ran. A fake VAD needs neither torch nor a microphone.
"""
import contextlib

import numpy as np
import pytest

from laris import audio_capture, config
from laris.vad_onnx import OnnxVadCapture

CHUNK_MS = 1000.0 * config.CHUNK_SAMPLES / config.SAMPLE_RATE  # 32ms


class ScriptedVad:
    """Returns the next probability from a list, then 0.0 forever."""

    def __init__(self, probabilities):
        self.probabilities = list(probabilities)
        self.resets = 0

    def reset(self):
        self.resets += 1

    def probability(self, _chunk):
        return self.probabilities.pop(0) if self.probabilities else 0.0


def drive(probabilities, monkeypatch, on_chunk=None):
    """Feed one chunk per scripted probability and collect the utterances."""
    chunks = len(probabilities)

    def fake_stream(callback):
        block = np.full((config.CHUNK_SAMPLES, 1), 0.1, dtype=np.float32)
        for _ in range(chunks):
            callback(block, config.CHUNK_SAMPLES, None, None)
        return contextlib.nullcontext()

    monkeypatch.setattr(audio_capture, "_open_stream", fake_stream)
    capture = OnnxVadCapture(vad=ScriptedVad(probabilities))
    turns = {"n": 0}

    def should_stop():
        turns["n"] += 1
        return turns["n"] > chunks + 5

    return [
        len(audio) / rate
        for audio, rate in capture.stream_utterances(
            should_stop=should_stop, on_chunk=on_chunk
        )
    ]


def _silence_chunks(ms):
    return [0.0] * (int(ms / CHUNK_MS) + 1)


def test_speech_then_silence_yields_one_utterance(monkeypatch):
    speech = [0.9] * 30                      # ~960ms, over the 400ms minimum
    got = drive(speech + _silence_chunks(config.VAD_MIN_SILENCE_MS), monkeypatch)
    assert len(got) == 1
    assert got[0] > config.MIN_SPEECH_DURATION_MS / 1000


def test_utterance_shorter_than_the_minimum_is_dropped(monkeypatch):
    # 5 chunks is 160ms, under MIN_SPEECH_DURATION_MS (400ms)
    got = drive([0.9] * 5 + _silence_chunks(config.VAD_MIN_SILENCE_MS), monkeypatch)
    assert got == []


def test_a_dip_that_is_not_silence_does_not_split_the_sentence(monkeypatch):
    """silero ends speech below threshold-0.15, not below threshold: with one
    rule the decision flaps around the boundary and chops a sentence in two."""
    between = config.VAD_THRESHOLD - 0.05      # under start, over end
    script = [0.9] * 20 + [between] * 20 + [0.9] * 20
    got = drive(script + _silence_chunks(config.VAD_MIN_SILENCE_MS), monkeypatch)
    assert len(got) == 1, f"expected one continuous utterance, got {got}"


def test_silence_shorter_than_the_gap_does_not_split(monkeypatch):
    half_gap = _silence_chunks(config.VAD_MIN_SILENCE_MS / 2 - CHUNK_MS)
    script = [0.9] * 20 + half_gap + [0.9] * 20
    got = drive(script + _silence_chunks(config.VAD_MIN_SILENCE_MS), monkeypatch)
    assert len(got) == 1


def test_two_sentences_separated_by_a_real_pause(monkeypatch):
    gap = _silence_chunks(config.VAD_MIN_SILENCE_MS + CHUNK_MS)
    script = [0.9] * 20 + gap + [0.9] * 20 + gap
    assert len(drive(script, monkeypatch)) == 2


def test_endless_speech_is_cut_at_the_maximum(monkeypatch):
    """Without the cap a stuck-open mic would buffer forever and never
    transcribe anything."""
    max_chunks = int(
        config.MAX_SPEECH_DURATION_S * config.SAMPLE_RATE / config.CHUNK_SAMPLES
    )
    got = drive([0.9] * (max_chunks + 10), monkeypatch)
    assert len(got) >= 1
    assert got[0] == pytest.approx(config.MAX_SPEECH_DURATION_S, abs=0.1)


def test_should_stop_is_honoured_in_total_silence(monkeypatch):
    """The only way to end a hands-free session is this poll; a blocking read
    would leave it stuck until someone spoke."""
    def fake_stream(callback):
        return contextlib.nullcontext()

    monkeypatch.setattr(audio_capture, "_open_stream", fake_stream)
    capture = OnnxVadCapture(vad=ScriptedVad([]))
    assert list(capture.stream_utterances(should_stop=lambda: True)) == []


def test_every_chunk_reaches_on_chunk(monkeypatch):
    """The orb amplitude is driven from this callback - if it stops, the orb
    freezes mid-sentence."""
    seen = []
    drive([0.9] * 10 + _silence_chunks(config.VAD_MIN_SILENCE_MS),
          monkeypatch, on_chunk=seen.append)
    assert len(seen) == 10 + len(_silence_chunks(config.VAD_MIN_SILENCE_MS))


def test_state_is_reset_between_utterances(monkeypatch):
    """Silero is recurrent: carrying state across a pause drifts the
    probabilities of the next sentence."""
    vad = ScriptedVad([0.9] * 20 + _silence_chunks(config.VAD_MIN_SILENCE_MS))

    def fake_stream(callback):
        block = np.full((config.CHUNK_SAMPLES, 1), 0.1, dtype=np.float32)
        for _ in range(40):
            callback(block, config.CHUNK_SAMPLES, None, None)
        return contextlib.nullcontext()

    monkeypatch.setattr(audio_capture, "_open_stream", fake_stream)
    capture = OnnxVadCapture(vad=vad)
    turns = {"n": 0}

    def should_stop():
        turns["n"] += 1
        return turns["n"] > 45

    list(capture.stream_utterances(should_stop=should_stop))
    # once at the start of the stream, once when the utterance closed
    assert vad.resets >= 2


class _ScriptedVad:
    """One probability per 512-sample window, in order."""

    def __init__(self, probs):
        self._probs = iter(probs)

    def reset(self):
        pass

    def probability(self, chunk):
        assert len(chunk) == 512
        return next(self._probs, 0.0)


def test_speech_spans_finds_each_utterance_with_padding():
    from laris.vad_onnx import speech_spans

    # 10 windows speech, 10 silence, 12 speech, 10 silence (512 samples each)
    probs = [0.9] * 10 + [0.0] * 10 + [0.9] * 12 + [0.0] * 10
    audio = np.zeros(512 * len(probs), dtype=np.float32)

    spans = speech_spans(audio, vad=_ScriptedVad(probs))

    pad = 16000 * 30 // 1000
    assert spans == [(0, 512 * 10 + pad), (512 * 20 - pad, 512 * 32 + pad)]


def test_speech_spans_drops_blips_and_bridges_short_pauses():
    from laris.vad_onnx import speech_spans

    # a 2-window blip (64 ms < 250 ms) is dropped; a 2-window dip inside
    # speech (64 ms < 100 ms of silence) does not split the utterance
    probs = [0.9] * 2 + [0.0] * 10 + [0.9] * 10 + [0.0] * 2 + [0.9] * 10 + [0.0] * 10
    audio = np.zeros(512 * len(probs), dtype=np.float32)

    spans = speech_spans(audio, vad=_ScriptedVad(probs), pad_ms=0)

    assert spans == [(512 * 12, 512 * 34)]


def test_speech_spans_keeps_speech_running_to_the_end_of_the_file():
    from laris.vad_onnx import speech_spans

    probs = [0.0] * 5 + [0.9] * 20
    audio = np.zeros(512 * len(probs), dtype=np.float32)

    assert speech_spans(audio, vad=_ScriptedVad(probs), pad_ms=0) == [(512 * 5, 512 * 25)]
