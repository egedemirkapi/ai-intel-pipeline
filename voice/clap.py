"""Two-clap detector.

A clap is a short, loud transient: RMS energy spikes well above the
ambient floor for one or two frames, then decays fast. Two such
transients within ``max_gap_ms`` (and at least ``min_gap_ms`` apart,
so a single clap's echo isn't double-counted) = a "two-clap" gesture.

This is intentionally simple amplitude thresholding — no ML. Tune
``rms_threshold`` in config.yaml to your room. After a trigger we go
quiet for ``cooldown_s`` so one gesture fires exactly one workflow.
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
        rms_threshold: float = 0.45,
        min_gap_ms: int = 150,
        max_gap_ms: int = 550,
        cooldown_s: float = 5.0,
    ) -> None:
        self.on_two_claps = on_two_claps
        self.rms_threshold = rms_threshold
        self.min_gap_s = min_gap_ms / 1000.0
        self.max_gap_s = max_gap_ms / 1000.0
        self.cooldown_s = cooldown_s

        self._last_transient_t: float = 0.0
        self._first_clap_t: float = 0.0
        self._armed = False          # True after one clap, waiting for the second
        self._cooldown_until: float = 0.0
        self._above = False          # hysteresis: are we currently in a transient

    def feed(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        if now < self._cooldown_until:
            return

        rms = float(np.sqrt(np.mean(np.square(frame)))) if frame.size else 0.0

        # Rising edge: frame crosses the threshold → count one transient.
        if rms >= self.rms_threshold and not self._above:
            self._above = True
            self._on_transient(now)
        elif rms < self.rms_threshold * 0.6:  # hysteresis release
            self._above = False

    def _on_transient(self, now: float) -> None:
        # Debounce: ignore transients too close to the previous one.
        if now - self._last_transient_t < self.min_gap_s:
            return
        self._last_transient_t = now

        if not self._armed:
            # First clap — arm and wait for a second.
            self._armed = True
            self._first_clap_t = now
            return

        # Second transient: is it within the window?
        gap = now - self._first_clap_t
        self._armed = False
        if self.min_gap_s <= gap <= self.max_gap_s:
            logger.info("two-clap gesture detected (gap=%.0fms)", gap * 1000)
            self._cooldown_until = now + self.cooldown_s
            try:
                self.on_two_claps()
            except Exception as exc:  # pragma: no cover
                logger.warning("clap handler error: %s", exc)
        # else: too slow — treat THIS transient as a new first clap
        elif gap > self.max_gap_s:
            self._armed = True
            self._first_clap_t = now
