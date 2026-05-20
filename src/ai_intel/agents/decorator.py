"""The @agent decorator — wraps a coroutine to record an AgentRun.

Usage:

    @agent("saturator")
    async def saturator(engine, **kw) -> AgentResult:
        ...

The wrapped function MUST accept `engine` as its first positional arg
(the SQLModel engine) and SHOULD return an ``AgentResult`` dict-like
with at least ``summary``. If it returns None, status='completed' with
no summary; if it raises, status='failed' with the exception captured.

The decorator records LLM cost only if the agent body uses
``call_llm`` from the runtime — currently we infer tokens/cost via the
AgentContext passed in. Simpler v1: the agent body returns the totals
itself in the result dict.
"""
from __future__ import annotations

import functools
import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypedDict

from sqlmodel import Session

from ai_intel.db.models import AgentRun

# Event-bus publication is best-effort: if the brain package isn't loaded
# (e.g. tests that don't depend on it, or a pure-pipeline invocation), the
# import-time hook is still cheap and the publish call is a no-op.
try:
    from ai_intel.brain.events import FleetEvent, get_event_bus
    _BUS_AVAILABLE = True
except Exception:  # pragma: no cover — only fires if brain pkg broken
    _BUS_AVAILABLE = False

logger = logging.getLogger(__name__)


class AgentResult(TypedDict, total=False):
    summary: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    auth_mode: str  # "oauth" | "api_key"
    output_pointer: str  # JSON-serializable pointer to output rows


AgentFunc = Callable[..., Awaitable[AgentResult | None]]


def agent(agent_id: str) -> Callable[[AgentFunc], AgentFunc]:
    """Decorate an async agent function with AgentRun bookkeeping.

    Side effect: publishes ``agent_started`` and ``agent_finished``
    events to the Jarvis Brain event bus so the frontend can re-render
    live without polling. Publishing is best-effort (swallows errors)
    so an event-bus issue never breaks an agent run.
    """

    def decorator(fn: AgentFunc) -> AgentFunc:
        @functools.wraps(fn)
        async def wrapper(engine, *args, **kwargs):
            run_id = _record_start(engine, agent_id)
            _publish_event("agent_started", agent_id=agent_id, run_id=run_id)
            try:
                result = await fn(engine, *args, **kwargs)
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
                _record_finish(engine, run_id, status="failed", error=err)
                _publish_event(
                    "agent_finished", agent_id=agent_id, run_id=run_id,
                    summary=f"failed: {type(exc).__name__}: {exc}",
                    payload={"status": "failed"},
                )
                raise
            _record_finish(engine, run_id, status="completed", result=result or {})
            _publish_event(
                "agent_finished", agent_id=agent_id, run_id=run_id,
                summary=(result or {}).get("summary"),
                payload={
                    "status": "completed",
                    "cost_usd": (result or {}).get("cost_usd", 0.0),
                    "prompt_tokens": (result or {}).get("prompt_tokens", 0),
                    "completion_tokens": (result or {}).get("completion_tokens", 0),
                },
            )
            return result

        # Expose the underlying function so tests can call it directly
        # if they want to skip the decorator.
        wrapper.__wrapped_agent_id__ = agent_id  # type: ignore[attr-defined]
        return wrapper

    return decorator


def _publish_event(
    event_type: str,
    *,
    agent_id: str,
    run_id: int,
    summary: str | None = None,
    payload: dict | None = None,
) -> None:
    """Best-effort publish to the Jarvis Brain event bus."""
    if not _BUS_AVAILABLE:
        return
    try:
        bus = get_event_bus()
        evt = FleetEvent(
            type=event_type,  # type: ignore[arg-type]
            agent_id=agent_id,
            run_id=run_id,
            summary=summary,
            payload=payload,
        )
        bus.publish(evt)
    except Exception as exc:  # pragma: no cover
        logger.debug("event_bus publish failed (non-fatal): %s", exc)


def _record_start(engine, agent_id: str) -> int:
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        row = AgentRun(
            agent_id=agent_id,
            status="running",
            started_at=now,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id  # type: ignore[return-value]


def _record_finish(
    engine,
    run_id: int,
    *,
    status: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    result = result or {}
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        row = s.get(AgentRun, run_id)
        if row is None:
            logger.error("AgentRun %d not found at finish", run_id)
            return
        row.status = status
        row.finished_at = now
        row.summary = (result.get("summary") or "")[:512] or None
        row.prompt_tokens = int(result.get("prompt_tokens", 0) or 0)
        row.completion_tokens = int(result.get("completion_tokens", 0) or 0)
        row.cost_estimate_usd = float(result.get("cost_usd", 0.0) or 0.0)
        row.auth_mode = result.get("auth_mode")
        row.output_pointer_json = (
            result.get("output_pointer") if result.get("output_pointer") else None
        )
        row.error = error[:2000] if error else None
        s.add(row)
        s.commit()
