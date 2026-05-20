"""Outbound speech queue — the Brain → voice tray reverse channel.

The voice tray is a separate process; nothing can push to it. Instead
the Brain holds a small queue of pending utterances. Anything that wants
Jarvis to speak unprompted — the scheduled briefing job, the fleet-event
narrator, a future caller — appends here (``POST /speak``); the voice
tray drains it by polling ``GET /speak/pending`` and speaks what it gets.

``narration_for()`` turns a FleetEvent into a spoken sentence (or None);
the Brain's narrator task uses it to feed live narration into the queue.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class Utterance:
    text: str
    kind: str  # "briefing" | "narration" | "manual"
    ts: float

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "kind": self.kind, "ts": self.ts}


class SpeakQueue:
    """Thread-safe, bounded FIFO of pending utterances.

    Bounded so a tray that's been offline for hours doesn't come back to
    a backlog of stale briefings — the oldest entries fall off.
    """

    def __init__(self, *, maxlen: int = 16) -> None:
        self._dq: deque[Utterance] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def push(self, text: str, *, kind: str = "manual") -> bool:
        """Queue an utterance. Returns False if the text was empty."""
        text = (text or "").strip()
        if not text:
            return False
        with self._lock:
            self._dq.append(Utterance(text=text, kind=kind, ts=time.time()))
        return True

    def drain(self) -> list[Utterance]:
        """Return all pending utterances and clear the queue."""
        with self._lock:
            items = list(self._dq)
            self._dq.clear()
        return items

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._dq)


# Module-level singleton, like the event bus.
_QUEUE: SpeakQueue | None = None


def get_speak_queue() -> SpeakQueue:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = SpeakQueue()
    return _QUEUE


def reset_speak_queue() -> None:
    """Test-only: drop the singleton so each test gets a fresh queue."""
    global _QUEUE
    _QUEUE = None


# ─── Fleet-event narration ──────────────────────────────────────────

# Only the genuinely interesting moments — narrating every agent tick
# would be exhausting. Kept deliberately small and tasteful.
_NARRATABLE = {"trend_synthesized", "idea_evaluated"}


def narration_for(event) -> str | None:
    """Phrase a FleetEvent for speech, or return None if it isn't worth
    interrupting the user for. Uses only ``type``/``summary`` so it never
    depends on payload internals."""
    if event.type not in _NARRATABLE:
        return None
    summary = (event.summary or "").strip()
    if not summary:
        return None
    if event.type == "trend_synthesized":
        return f"New trend detected. {summary}"
    if event.type == "idea_evaluated":
        return f"An idea was just evaluated. {summary}"
    return None
