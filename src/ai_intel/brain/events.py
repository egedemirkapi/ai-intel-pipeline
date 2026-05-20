"""In-process event bus for live fleet visibility.

The @agent decorator publishes ``FleetEvent`` instances on entry/exit
so the Brain's WebSocket /events endpoint can stream them to the
frontend in real time. Pure asyncio — no external broker, no Redis.

Pattern is fan-out: every subscriber gets every event. Subscribers are
asyncio Queues so a slow subscriber doesn't block the publisher (events
are dropped from that subscriber's queue if it fills, never from the
bus globally).

The bus is a module-level singleton retrieved via ``get_event_bus()``
so the @agent decorator can publish without needing to be handed a bus
instance.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

logger = logging.getLogger(__name__)

EventType = Literal[
    "agent_started",
    "agent_finished",
    "idea_proposed",
    "idea_evaluated",
    "trend_synthesized",
    "intel_collected",
    "workflow_started",
    "workflow_finished",
    "voice_state",
]


@dataclass
class FleetEvent:
    """A single observable event in the fleet. JSON-serializable."""
    type: EventType
    ts: float = field(default_factory=time.time)  # unix epoch seconds
    agent_id: str | None = None
    run_id: int | None = None
    summary: str | None = None
    payload: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    """Async fan-out bus.

    Per-subscriber asyncio.Queue with a bounded size. If a subscriber is
    slow and its queue fills, ``publish`` drops the event for THAT
    subscriber (and logs) rather than blocking the publisher.
    """

    def __init__(self, *, queue_maxsize: int = 256) -> None:
        self._subscribers: set[asyncio.Queue[FleetEvent]] = set()
        self._queue_maxsize = queue_maxsize
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[FleetEvent]:
        """Register a new subscriber queue. Caller awaits queue.get()."""
        q: asyncio.Queue[FleetEvent] = asyncio.Queue(maxsize=self._queue_maxsize)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[FleetEvent]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    def publish(self, event: FleetEvent) -> None:
        """Non-blocking publish. Safe to call from sync code via
        ``asyncio.get_running_loop().call_soon_threadsafe(...)`` if
        called outside the event loop — but the @agent decorator
        publishes from within an async coroutine so the direct call
        works fine.
        """
        dropped = 0
        for q in tuple(self._subscribers):  # tuple snapshot to be safe
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dropped += 1
        if dropped:
            logger.debug(
                "event_bus: dropped event for %d slow subscriber(s)", dropped,
            )

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Module-level singleton. The @agent decorator imports get_event_bus()
# and calls .publish() — no plumbing required for the publisher side.
_BUS: EventBus | None = None


def get_event_bus() -> EventBus:
    global _BUS
    if _BUS is None:
        _BUS = EventBus()
    return _BUS


def reset_event_bus() -> None:
    """Test-only: clear the singleton so each test gets a fresh bus."""
    global _BUS
    _BUS = None
