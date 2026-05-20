"""Speak poller — drains the Brain's outbound speech queue.

The Brain can't push to the tray, so the tray pulls: this thread polls
``GET /speak/pending`` every few seconds and hands any utterances to a
callback (which queues them on the tray's worker for the TTS engine).

This is what lets Jarvis speak *unprompted* — the scheduled daily brief
and live fleet narration both arrive through here.
"""
from __future__ import annotations

import logging
import threading

import httpx

logger = logging.getLogger(__name__)


class SpeakPoller:
    """Polls the Brain speak queue and forwards utterances to a callback."""

    def __init__(self, brain_url: str, on_utterance, *, interval_s: float = 4.0) -> None:
        self.brain_url = brain_url.rstrip("/")
        self.on_utterance = on_utterance  # callable(text: str, kind: str) -> None
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="jarvis-speak-poller",
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                r = httpx.get(f"{self.brain_url}/speak/pending", timeout=10.0)
                r.raise_for_status()
                for u in r.json().get("utterances", []):
                    text = (u.get("text") or "").strip()
                    if text:
                        self.on_utterance(text, u.get("kind", "manual"))
            except Exception as exc:
                logger.debug("speak poll failed: %s", exc)
            self._stop.wait(self.interval_s)
