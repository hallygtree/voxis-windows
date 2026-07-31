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
