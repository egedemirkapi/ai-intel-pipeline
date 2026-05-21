"""Tests for the crest-factor clap detector (voice/clap.py).

The whole point of the rewrite: a clap — a sharp, spiky impulse — fires
the two-clap gesture, but speech — sustained and smooth — never does,
even when the two are equally loud. The old RMS-loudness detector could
not tell them apart, so every spoken word triggered the welcome routine.
These tests prove the separation holds.
"""
from __future__ import annotations

import numpy as np
import pytest

from voice.clap import ClapDetector

_FRAME = 1280  # 80 ms at 16 kHz — one mic frame


def _clap_frame(peak: float = 1.0) -> np.ndarray:
    """A clap: near-silence with one short, sharp spike. Tiny RMS, huge
    peak → very high crest factor — the signature of an impulse."""
    f = np.zeros(_FRAME, dtype=np.float32)
    f[100:120] = peak  # ~1 ms of energy
    return f


def _speech_frame(amp: float = 0.6) -> np.ndarray:
    """Speech stand-in: a sustained tone filling the whole frame. Its
    peak is only ~1.4× its RMS — a low crest factor, unlike a clap.
    A sine's crest factor is the same at any volume, so a LOUD speech
    frame is still rejected — loudness is irrelevant, shape is not."""
    t = np.arange(_FRAME, dtype=np.float32)
    return (amp * np.sin(2 * np.pi * 220 * t / 16000)).astype(np.float32)


def _silence() -> np.ndarray:
    return np.zeros(_FRAME, dtype=np.float32)


class _Clock:
    """A controllable stand-in for time.monotonic()."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, secs: float) -> None:
        self.t += secs


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr("voice.clap.time.monotonic", c)
    return c


def test_two_claps_fire_the_gesture(clock):
    fired: list[int] = []
    det = ClapDetector(lambda: fired.append(1))
    # First clap — a spike frame, then a silent frame for the falling edge.
    det.feed(_clap_frame())
    clock.advance(0.08)
    det.feed(_silence())
    clock.advance(0.30)
    # Second clap, 300 ms later — inside the two-clap window.
    det.feed(_clap_frame())
    clock.advance(0.08)
    det.feed(_silence())
    assert fired == [1]


def test_speech_never_fires(clock):
    """A long run of speech frames must not produce a single transient —
    this is the bug the rewrite fixes."""
    fired: list[int] = []
    det = ClapDetector(lambda: fired.append(1))
    for _ in range(60):
        det.feed(_speech_frame(amp=0.6))
        clock.advance(0.08)
    assert fired == []


def test_loud_speech_still_never_fires(clock):
    """Even very loud speech (high amplitude) is rejected — the detector
    keys on shape (crest factor), not loudness."""
    fired: list[int] = []
    det = ClapDetector(lambda: fired.append(1))
    for _ in range(60):
        det.feed(_speech_frame(amp=0.95))
        clock.advance(0.08)
    assert fired == []


def test_single_clap_does_not_fire(clock):
    fired: list[int] = []
    det = ClapDetector(lambda: fired.append(1))
    det.feed(_clap_frame())
    clock.advance(0.08)
    det.feed(_silence())
    assert fired == []


def test_two_claps_too_far_apart_do_not_fire(clock):
    """Two claps a full second apart are not a deliberate double-clap."""
    fired: list[int] = []
    det = ClapDetector(lambda: fired.append(1))
    det.feed(_clap_frame())
    clock.advance(0.08)
    det.feed(_silence())
    clock.advance(1.0)  # well past max_gap_ms
    det.feed(_clap_frame())
    clock.advance(0.08)
    det.feed(_silence())
    assert fired == []
