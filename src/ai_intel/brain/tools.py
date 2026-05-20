"""Tool registry — the surface the Brain's conversational LLM can call.

Each tool is:
    name        — globally unique; checked against ~/.jarvis/tools.toml
    description — what the LLM should know about WHEN to call it
    json_schema — Anthropic tool-use compatible parameter schema
    handler     — async function: (engine, **kwargs) -> dict

Every tool invocation flows through ``invoke()`` which:
    1. Looks up the tool by name
    2. Checks the capability layer (allow/deny)
    3. On deny: returns a {"refused": ..., "approval_id": ...} payload
       and queues an approval request, never invokes the handler
    4. On allow: runs the handler, returns whatever it returned

The tools here are LIVE READS over the existing DB + the agent fleet.
None of them touch the OS or external services directly — those land
in the workflow engine (Phase 14) or Google collectors (Phase 13).
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from sqlmodel import Session, desc, func, select

from ai_intel.db.models import (
    AgentRun,
    IdeaCandidate,
    Item,
    TrendSynthesis,
)
from ai_intel.jarvis.permissions import is_allowed, request_approval

logger = logging.getLogger(__name__)


ToolHandler = Callable[..., Awaitable[dict[str, Any]] | dict[str, Any]]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: ToolHandler


# ─── Handlers ──────────────────────────────────────────────────────


async def _h_agents_status(engine) -> dict[str, Any]:
    with Session(engine) as s:
        agent_ids = list(s.exec(select(AgentRun.agent_id).distinct()).all())
        out: dict[str, Any] = {}
        for aid in agent_ids:
            latest = s.exec(
                select(AgentRun)
                .where(AgentRun.agent_id == aid)
                .order_by(desc(AgentRun.started_at))
                .limit(1)
            ).first()
            count = s.exec(
                select(func.count(AgentRun.id))
                .where(AgentRun.agent_id == aid)
            ).first()
            out[aid] = {
                "total_runs": int(count or 0),
                "latest_status": latest.status if latest else None,
                "latest_summary": (latest.summary or "")[:200] if latest else None,
                "latest_started_at": (
                    latest.started_at.isoformat() if latest and latest.started_at
                    else None
                ),
            }
    return {"agents": out}


async def _h_agents_tail(
    engine, *, agent_id: str | None = None, limit: int = 5,
) -> dict[str, Any]:
    with Session(engine) as s:
        q = select(AgentRun).order_by(desc(AgentRun.started_at)).limit(limit)
        if agent_id:
            q = q.where(AgentRun.agent_id == agent_id)
        rows = list(s.exec(q))
    return {
        "runs": [
            {
                "id": r.id,
                "agent_id": r.agent_id,
                "status": r.status,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "summary": r.summary,
                "cost_usd": r.cost_estimate_usd,
            }
            for r in rows
        ],
    }


async def _h_agents_run(engine, *, agent_id: str, **agent_kwargs) -> dict[str, Any]:
    """Trigger an agent run. Looks up in AGENT_REGISTRY."""
    from ai_intel.agents import AGENT_REGISTRY
    if agent_id not in AGENT_REGISTRY:
        return {
            "error": f"unknown agent_id={agent_id!r}",
            "known": sorted(AGENT_REGISTRY.keys()),
        }
    fn = AGENT_REGISTRY[agent_id]
    # Drop None / unknown kwargs the agent might not accept. Keep simple
    # types only — the LLM should not be invoking with arbitrary objects.
    clean_kw = {k: v for k, v in agent_kwargs.items() if v is not None}
    try:
        result = await fn(engine, **clean_kw)
    except TypeError as exc:
        return {"error": f"agent rejected kwargs: {exc}"}
    return result or {"summary": "(no result returned)"}


async def _h_ideas_list(
    engine,
    *,
    status: str | None = None,
    min_score: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    with Session(engine) as s:
        q = select(IdeaCandidate).order_by(desc(IdeaCandidate.proposed_at))
        if status:
            q = q.where(IdeaCandidate.status == status)
        if min_score is not None:
            q = q.where(IdeaCandidate.evaluator_score >= min_score)
        rows = list(s.exec(q.limit(limit)))
    return {
        "ideas": [
            {
                "id": r.id,
                "idea_text": r.idea_text,
                "status": r.status,
                "evaluator_score": r.evaluator_score,
                "evaluator_verdict": r.evaluator_verdict,
                "tech_basis": r.tech_basis,
                "proposed_at": r.proposed_at.isoformat() if r.proposed_at else None,
            }
            for r in rows
        ],
    }


async def _h_ideas_show(engine, *, idea_id: int) -> dict[str, Any]:
    with Session(engine) as s:
        r = s.get(IdeaCandidate, idea_id)
    if r is None:
        return {"error": f"no idea with id={idea_id}"}
    try:
        blob = json.loads(r.persona_critiques_json or "{}")
    except (json.JSONDecodeError, TypeError):
        blob = {}
    detail = blob.pop("_proposer_detail", {})
    return {
        "id": r.id,
        "idea_text": r.idea_text,
        "status": r.status,
        "evaluator_score": r.evaluator_score,
        "evaluator_verdict": r.evaluator_verdict,
        "proposer_detail": detail,
        "persona_critiques": blob,
    }


async def _h_trends_latest(
    engine, *, limit: int = 8,
) -> dict[str, Any]:
    with Session(engine) as s:
        rows = list(s.exec(
            select(TrendSynthesis)
            .where(TrendSynthesis.status == "active")
            .order_by(desc(TrendSynthesis.generated_at))
            .limit(limit)
        ))
    return {
        "trends": [
            {
                "id": r.id,
                "cluster_label": r.cluster_label,
                "underlying_shift": r.underlying_shift,
                "new_capability": r.new_capability,
                "momentum": r.momentum,
            }
            for r in rows
        ],
    }


async def _h_intel_recent(
    engine, *, hours: int = 24, source: str | None = None, limit: int = 20,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with Session(engine) as s:
        q = (
            select(Item)
            .where(Item.collected_at >= cutoff)
            .where(Item.source != "founder_brain")
            .where(Item.source != "failure_corpus")
            .order_by(desc(Item.collected_at))
            .limit(limit)
        )
        if source:
            q = q.where(Item.source == source)
        rows = list(s.exec(q))
    return {
        "items": [
            {
                "id": it.id,
                "source": it.source,
                "title": it.title,
                "url": it.url,
                "collected_at": it.collected_at.isoformat() if it.collected_at else None,
                "ai_relevance": it.ai_relevance,
            }
            for it in rows
        ],
    }


async def _h_memory_recall(
    engine, *, query: str, k: int = 5, source: str | None = None,
) -> dict[str, Any]:
    """Semantic recall over the existing memory store. Defers to retrieve.recall."""
    from ai_intel.memory.retrieve import recall
    hits = recall(engine, query, k=k, source=source, log_query=False)
    return {
        "hits": [
            {
                "score": round(h.score, 4),
                "title": h.title,
                "source": h.source,
                "url": h.url,
                "snippet": h.snippet,
            }
            for h in hits
        ],
    }


async def _h_workflow_run(engine, *, name: str) -> dict[str, Any]:
    """Run a named YAML workflow (e.g. morning_brief, homework_check)."""
    from ai_intel.workflows import run_workflow
    return await run_workflow(engine, name)


async def _h_workflow_list(engine) -> dict[str, Any]:
    """List the available YAML workflows."""
    from ai_intel.workflows import list_workflows
    return {"workflows": list_workflows()}


async def _h_classroom_read(engine, *, days_ahead: int = 7) -> dict[str, Any]:
    """On-demand fresh fetch of Google Classroom coursework + announcements.

    Does a LIVE pull (not a stale DB read) so 'what's my homework' is
    always current. Returns assignments with their due dates so the LLM
    can filter to 'this week'.
    """
    from datetime import datetime, timedelta, timezone
    from ai_intel.collectors.google_classroom import GoogleClassroomCollector
    from ai_intel.google_auth import has_token

    if not has_token():
        return {
            "error": "Google not connected. Run scripts/setup_google_auth.py first.",
            "items": [],
        }
    collector = GoogleClassroomCollector()
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    raw_items = await collector.fetch_since(cutoff)
    assignments = []
    announcements = []
    for it in raw_items:
        kind = (it.raw or {}).get("kind")
        entry = {
            "title": it.title,
            "course": (it.raw or {}).get("course"),
            "due_date": (it.raw or {}).get("due_date"),
            "url": it.url,
            "body": (it.body or "")[:500],
        }
        if kind == "assignment":
            assignments.append(entry)
        else:
            announcements.append(entry)
    return {
        "assignments": assignments,
        "announcements": announcements,
        "days_ahead_hint": days_ahead,
        "note": "due_date is ISO format or null; filter client-side for the window the user asked about",
    }


async def _h_calendar_read(engine, *, days_ahead: int = 7) -> dict[str, Any]:
    """On-demand fresh fetch of upcoming Google Calendar events.

    LIVE pull so 'what's on my calendar' is always current. Returns
    events with ISO start/end so the LLM can filter to the day asked.
    """
    from ai_intel.collectors.google_calendar import GoogleCalendarCollector
    from ai_intel.google_auth import has_token

    if not has_token():
        return {
            "error": "Google not connected. Run scripts/setup_google_auth.py first.",
            "events": [],
        }
    collector = GoogleCalendarCollector(days_ahead=days_ahead)
    raw_items = await collector.fetch_since(datetime.now(timezone.utc))
    events = []
    for it in raw_items:
        meta = it.raw or {}
        events.append({
            "title": it.title,
            "start": meta.get("start"),
            "end": meta.get("end"),
            "location": meta.get("location"),
            "url": it.url,
        })
    return {
        "events": events,
        "count": len(events),
        "days_ahead": days_ahead,
        "note": "start/end are ISO strings; filter to the window the user asked about",
    }


async def _h_email_read(engine, *, max_messages: int = 15) -> dict[str, Any]:
    """On-demand fresh fetch of recent Gmail inbox messages.

    LIVE pull. Returns subject + sender + snippet only (never full
    bodies) so 'any new emails' is answered without a privacy footprint.
    """
    from ai_intel.collectors.google_gmail import GoogleGmailCollector
    from ai_intel.google_auth import has_token

    if not has_token():
        return {
            "error": "Google not connected. Run scripts/setup_google_auth.py first.",
            "messages": [],
        }
    collector = GoogleGmailCollector(max_messages=max_messages)
    raw_items = await collector.fetch_since(datetime.now(timezone.utc))
    messages = []
    for it in raw_items:
        meta = it.raw or {}
        messages.append({
            "subject": it.title,
            "from": meta.get("sender"),
            "received_at": it.published_at.isoformat() if it.published_at else None,
            "preview": it.body,
            "url": it.url,
        })
    return {"messages": messages, "count": len(messages)}


async def _h_brief_get(engine) -> dict[str, Any]:
    """Assemble the user's current briefing — top news, calendar,
    homework and interest-based suggestions, plus a spoken summary."""
    from ai_intel.think.brief import build_brief

    return await build_brief(engine)


async def _h_context_app(engine) -> dict[str, Any]:
    """What app/window the user is currently focused on."""
    from ai_intel.brain.context import get_current_context

    ctx = get_current_context()
    if not ctx:
        return {"context": None, "note": "No foreground app has been reported yet."}
    return {"context": ctx}


# ─── Tool registry ─────────────────────────────────────────────────


def build_registry() -> dict[str, Tool]:
    """All Brain tools, named to match entries in tools.toml.

    The capability layer sees the dotted name (e.g. ``agents.status``)
    when deciding allow vs deny. Defaults are added to tools.toml so
    these all work out of the box.
    """
    return {
        "agents.status": Tool(
            name="agents.status",
            description=(
                "Get a live one-line summary per agent in the fleet "
                "(saturator, synthesizer, proposer, evaluator, "
                "weekly_ideation, collector). Use this when the user "
                "asks 'what's the fleet doing' or 'are the agents okay'."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=_h_agents_status,
        ),
        "agents.tail": Tool(
            name="agents.tail",
            description=(
                "Read the N most recent agent runs, optionally filtered "
                "by agent_id. Use this when the user asks 'what did "
                "the proposer do last' or 'show recent activity'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Filter by agent_id, e.g. 'proposer'"},
                    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
                },
            },
            handler=_h_agents_tail,
        ),
        "agents.run": Tool(
            name="agents.run",
            description=(
                "Trigger a backend agent to run NOW. agent_id must be "
                "one of: saturator, synthesizer, proposer, evaluator, "
                "weekly_ideation. Use only when the user explicitly "
                "asks to run the pipeline (e.g. 'go ahead, run the "
                "process and give me 3 ideas')."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "n_candidates": {"type": "integer", "description": "(weekly_ideation only) how many ideas"},
                    "topic": {"type": "string", "description": "(saturator only) topic to assess"},
                    "persona_id": {"type": "string", "description": "(proposer only) founder persona"},
                },
                "required": ["agent_id"],
            },
            handler=_h_agents_run,
        ),
        "ideas.list": Tool(
            name="ideas.list",
            description=(
                "List recent IdeaCandidate rows. Filter by status "
                "(proposed|killed|needs_work|borderline|escalated) or "
                "by min_score. Use this when the user asks 'show me "
                "the ideas' or 'what's escalated'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "min_score": {"type": "integer"},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
                },
            },
            handler=_h_ideas_list,
        ),
        "ideas.show": Tool(
            name="ideas.show",
            description=(
                "Full critique chain for ONE candidate by id — "
                "proposer's reasoning + all 6 persona subscores + "
                "kill criterion. Use this when the user wants details "
                "on a specific idea."
            ),
            input_schema={
                "type": "object",
                "properties": {"idea_id": {"type": "integer"}},
                "required": ["idea_id"],
            },
            handler=_h_ideas_show,
        ),
        "trends.latest": Tool(
            name="trends.latest",
            description=(
                "The synthesizer's current META-PATTERN trends — "
                "convergent shifts across the recent ecosystem. Each "
                "trend has a label + underlying shift + new capability "
                "+ momentum. Use when the user asks 'what's emerging' "
                "or 'what's the world doing right now'."
            ),
            input_schema={
                "type": "object",
                "properties": {"limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 50}},
            },
            handler=_h_trends_latest,
        ),
        "intel.recent": Tool(
            name="intel.recent",
            description=(
                "Recent intel items collected by the 24/7 pipeline — "
                "tech news, HN/Reddit posts, RSS articles. Filter by "
                "source (hn, reddit:*, rss:*, google_news) or hours."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "default": 24, "minimum": 1, "maximum": 720},
                    "source": {"type": "string"},
                    "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 200},
                },
            },
            handler=_h_intel_recent,
        ),
        "memory.recall": Tool(
            name="memory.recall",
            description=(
                "Semantic search across the user's memory (intel + "
                "founder corpus + failure corpus + personal notes). "
                "Best when the user asks 'what was I reading about X' "
                "or 'what does the corpus say on Y'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                    "source": {"type": "string", "description": "Optional source filter (e.g. 'founder_brain', 'failure_corpus')"},
                },
                "required": ["query"],
            },
            handler=_h_memory_recall,
        ),
        "gworkspace.read_classroom": Tool(
            name="gworkspace.read_classroom",
            description=(
                "Fetch the user's Google Classroom coursework + "
                "announcements LIVE (read-only). Use this for 'what's "
                "my homework', 'what's due this week', 'any class "
                "announcements'. Returns assignments with ISO due "
                "dates — filter to the window the user asked for."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "default": 7, "minimum": 1, "maximum": 60},
                },
            },
            handler=_h_classroom_read,
        ),
        "gworkspace.read_calendar": Tool(
            name="gworkspace.read_calendar",
            description=(
                "Fetch the user's upcoming Google Calendar events LIVE "
                "(read-only). Use for 'what's on my calendar', 'what "
                "does my day look like', 'am I free tomorrow'. Returns "
                "events with ISO start/end times — filter to the window "
                "the user asked for."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "default": 7, "minimum": 1, "maximum": 60},
                },
            },
            handler=_h_calendar_read,
        ),
        "gworkspace.read_email": Tool(
            name="gworkspace.read_email",
            description=(
                "Fetch the user's recent Gmail inbox messages LIVE "
                "(read-only — subject, sender and a short snippet only, "
                "never full bodies). Use for 'any new emails', 'what's "
                "in my inbox', 'did I get anything important'."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "max_messages": {"type": "integer", "default": 15, "minimum": 1, "maximum": 50},
                },
            },
            handler=_h_email_read,
        ),
        "brief.get": Tool(
            name="brief.get",
            description=(
                "Assemble the user's briefing — the top recent tech news, "
                "their upcoming calendar, homework due soon, and "
                "suggestions matched to their interests. Use when the "
                "user asks 'what's my briefing', 'brief me', 'what "
                "should I know today', or 'catch me up'."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=_h_brief_get,
        ),
        "context.app": Tool(
            name="context.app",
            description=(
                "What app or window the user is currently focused on. "
                "Use when the user asks 'what am I doing', 'what am I "
                "working on', or to tailor an answer to their current "
                "context (e.g. they're in an IDE vs a browser)."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=_h_context_app,
        ),
        "workflow.run": Tool(
            name="workflow.run",
            description=(
                "Run a named YAML automation workflow — e.g. "
                "'morning_brief' (refresh trends + 3 ideas), "
                "'homework_check' (Classroom summary), 'clap_default' "
                "(open study tabs). Use when the user says 'run my "
                "<X> workflow' or 'do my morning brief'."
            ),
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            handler=_h_workflow_run,
        ),
        "workflow.list": Tool(
            name="workflow.list",
            description="List the available automation workflows by name.",
            input_schema={"type": "object", "properties": {}},
            handler=_h_workflow_list,
        ),
    }


# ─── Capability-gated invoke ───────────────────────────────────────


async def invoke(
    registry: dict[str, Tool],
    engine,
    name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Resolve + permission-check + run one tool.

    Returns either:
        the handler's return dict, OR
        {"refused": "...", "approval_id": "..."} if denied
    """
    tool = registry.get(name)
    if tool is None:
        return {"error": f"unknown tool name={name!r}"}
    if not is_allowed(name):
        # Queue an approval entry; user can review with `jarvis approve list`
        approval_id = request_approval(
            name, args, reason="LLM requested an unauthorized tool",
        )
        logger.info("tool refused: %s (approval=%s)", name, approval_id)
        return {
            "refused": (
                f"Tool {name!r} is denied by current policy. "
                f"An approval request was queued."
            ),
            "approval_id": approval_id,
        }
    # Run handler — may be sync or async
    fn = tool.handler
    try:
        out = fn(engine, **args)
        if inspect.isawaitable(out):
            out = await out
    except TypeError as exc:
        return {"error": f"tool args invalid: {exc}"}
    except Exception as exc:
        logger.exception("tool handler raised: %s", name)
        return {"error": f"{type(exc).__name__}: {exc}"}
    return out


# Anthropic's tool-name regex is ^[a-zA-Z0-9_-]{1,128}$ — it rejects the
# dots in our capability-namespaced names (e.g. "agents.status"). We map
# '.' <-> '-' for the API surface. This is a safe bijection because no
# tool name contains a natural hyphen (underscores, as in
# "gworkspace.read_classroom", are preserved untouched).


def _api_name(internal: str) -> str:
    """Internal dotted name -> Anthropic-safe name."""
    return internal.replace(".", "-")


def _internal_name(api: str) -> str:
    """Anthropic-safe name -> internal dotted name."""
    return api.replace("-", ".")


def anthropic_tool_specs(registry: dict[str, Tool]) -> list[dict[str, Any]]:
    """Render the registry into Anthropic's tool-use shape.

    Tool names are emitted in the API-safe form (dots -> hyphens). The
    chat loop must call ``resolve_api_name()`` on any tool_use block's
    name before passing it to ``invoke()``.
    """
    return [
        {
            "name": _api_name(t.name),
            "description": t.description,
            "input_schema": t.input_schema,
        }
        for t in registry.values()
    ]


def resolve_api_name(api_name: str) -> str:
    """Convert an Anthropic tool_use name back to the internal dotted name."""
    return _internal_name(api_name)
