"""Two-clap detector — tells a hand-clap apart from speech.

A clap is an *impulse*: a near-instant pressure spike, broadband, that
decays within tens of milliseconds. Speech is sustained and
quasi-periodic. The two overlap badly in loudness — a normal sentence
and a clap can have the same RMS — so a plain loudness threshold either
misses real claps or fires on every spoken word. That is exactly the
bug this replaces.

The discriminator is the **crest factor**: peak sample ÷ RMS within an
80 ms frame. A clap concentrates its energy into one tiny spike, so its
peak towers over its RMS — crest factor easily 8-30. Speech fills the
frame evenly, so its peak is only ~3-4× its RMS. A frame counts as a
clap transient only when all three hold:

    peak  >= peak_min          (genuinely loud at its peak)
    peak / rms >= crest_min    (spiky, not sustained — i.e. not speech)
    it is short                (a clap lasts 1-3 frames, speech does not)

Two such transients within ``max_gap_ms`` = a "two-clap" gesture. Tune
``peak_min`` / ``crest_min`` to your room with ``python -m voice.diagnose``;
the calibration measures both your claps and your speech and picks a
threshold that sits cleanly between them.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import numpy as np

logger = logging.getLogger(__name__)


class ClapDetector:
    """Feed it mic frames; it calls ``on_two_claps`` on the gesture."""

    def __init__(
        self,
        on_two_claps: Callable[[], None],
        *,
        peak_min: float = 0.18,
        crest_min: float = 6.0,
        min_gap_ms: int = 120,
        max_gap_ms: int = 650,
        cooldown_s: float = 5.0,
        max_transient_frames: int = 4,
    ) -> None:
        self.on_two_claps = on_two_claps
        self.peak_min = peak_min
        self.crest_min = crest_min
        self.min_gap_s = min_gap_ms / 1000.0
        self.max_gap_s = max_gap_ms / 1000.0
        self.cooldown_s = cooldown_s
        self.max_transient_frames = max_transient_frames

        self._last_transient_t: float = 0.0
        self._first_clap_t: float = 0.0
        self._armed = False           # True after one clap, awaiting the second
        self._cooldown_until: float = 0.0
        self._above = False           # currently inside a clap-like transient
        self._above_frames = 0        # how many frames the transient has lasted
        self._pending_t: float = 0.0  # when the current transient began
        self._above_peak: float = 0.0   # loudest peak seen during the transient
        self._above_crest: float = 0.0  # highest crest factor seen during it

    def feed(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        if now < self._cooldown_until or not frame.size:
            return

        rms = float(np.sqrt(np.mean(np.square(frame))))
        peak = float(np.max(np.abs(frame)))
        crest = peak / rms if rms > 1e-6 else 0.0

        # A clap frame: loud AND spiky. Speech is loud but NOT spiky, so
        # the crest-factor test rejects it — this is the whole point.
        is_clap_frame = peak >= self.peak_min and crest >= self.crest_min

        if is_clap_frame:
            if not self._above:
                # Rising edge — a transient begins.
                self._above = True
                self._above_frames = 1
                self._pending_t = now
                self._above_peak = peak
                self._above_crest = crest
            else:
                self._above_frames += 1
                self._above_peak = max(self._above_peak, peak)
                self._above_crest = max(self._above_crest, crest)
        elif self._above:
            # Falling edge — the transient ended. Count it only if it was
            # SHORT; a long run of spiky frames is machine noise, not a
            # clap. The timestamp is the transient's start, so the gap
            # between two claps is measured consistently.
            self._above = False
            if self._above_frames <= self.max_transient_frames:
                self._on_transient(self._pending_t)
            else:
                logger.debug(
                    "clap: ignored a %d-frame sustained transient (not a clap)",
                    self._above_frames,
                )
            self._above_frames = 0

    def _on_transient(self, when: float) -> None:
        # Debounce: ignore a transient too close to the previous one — a
        # clap's reverberant tail can briefly re-cross the threshold.
        if when - self._last_transient_t < self.min_gap_s:
            return
        self._last_transient_t = when
        # Visibility: every accepted transient is logged with its shape,
        # so the tray console shows clap activity (and you can see that a
        # spoken word is correctly NOT being counted).
        logger.info(
            "clap: transient (peak=%.2f crest=%.1f)",
            self._above_peak, self._above_crest,
        )

        if not self._armed:
            # First clap — arm and wait for a second.
            self._armed = True
            self._first_clap_t = when
            return

        # Second transient — is it inside the two-clap window?
        gap = when - self._first_clap_t
        self._armed = False
        if self.min_gap_s <= gap <= self.max_gap_s:
            logger.info("two-clap gesture detected (gap=%.0fms)", gap * 1000)
            self._cooldown_until = time.monotonic() + self.cooldown_s
            try:
                self.on_two_claps()
            except Exception as exc:  # pragma: no cover
                logger.warning("clap handler error: %s", exc)
        elif gap > self.max_gap_s:
            # Too slow — treat THIS transient as a fresh first clap.
            self._armed = True
            self._first_clap_t = when
