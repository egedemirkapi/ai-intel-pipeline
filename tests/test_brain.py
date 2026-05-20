"""Tests for the Jarvis Brain FastAPI service.

Covers:
- Read-only routes return the right shape over a seeded in-memory DB
- Event bus publish/subscribe fan-out works under concurrent subscribers
- The @agent decorator publishes start + finish events
- WebSocket /events streams those events to connected clients
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from ai_intel.brain.events import EventBus, FleetEvent, get_event_bus, reset_event_bus
from ai_intel.db.models import (
    AgentRun,
    IdeaCandidate,
    Item,
    TrendSynthesis,
)


# ─── In-memory DB fixture pointing the brain app at a temp file ──────


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Build a temp SQLite file and point the brain app's _DB_PATH at it."""
    path = tmp_path / "items.db"
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    # Seed a small dataset
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add_all([
            AgentRun(
                agent_id="proposer", status="completed",
                started_at=now - timedelta(hours=1),
                finished_at=now - timedelta(minutes=55),
                summary="proposed=1",
                cost_estimate_usd=0.01,
            ),
            AgentRun(
                agent_id="synthesizer", status="completed",
                started_at=now - timedelta(hours=2),
                finished_at=now - timedelta(hours=2, minutes=-2),
                summary="8 trends",
                cost_estimate_usd=0.02,
            ),
            Item(
                source="hn", url="https://example.test/x",
                url_hash="abc123", title="Test story",
                body="body", published_at=now, collected_at=now,
            ),
            IdeaCandidate(
                proposed_at=now,
                idea_text="A focused idea",
                tech_basis="some tech",
                evaluator_score=70,
                evaluator_verdict="needs_work",
                status="needs_work",
                persona_critiques_json=json.dumps({
                    "_proposer_detail": {"wedge": "indie devs"},
                    "paul_graham": {"subscore": 72, "critique": "real schlep"},
                }),
            ),
            TrendSynthesis(
                generated_at=now,
                window_start=now - timedelta(days=14),
                window_end=now,
                cluster_label="Local LLM inference",
                member_item_ids_json=json.dumps([1, 2, 3]),
                underlying_shift="MoE landing on consumer GPUs",
                new_capability="Indie devs can run frontier-class dialogue locally",
                momentum="rising_fast",
                convergence_with_json=json.dumps([]),
                status="active",
            ),
        ])
        s.commit()
    monkeypatch.setenv("JARVIS_DB_PATH", str(path))
    # Force the app module to re-resolve _DB_PATH on next import
    import importlib
    import ai_intel.brain.app as app_mod
    importlib.reload(app_mod)
    yield path


@pytest.fixture
def client(db_path):
    """TestClient against a fresh brain app pointed at the seeded DB."""
    reset_event_bus()
    from ai_intel.brain.app import create_app
    app = create_app()
    with TestClient(app) as c:
        yield c


# ─── Read-only route tests ───────────────────────────────────────────


def test_root_health(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "jarvis-brain"
    assert "db_path" in body


def test_agents_status_lists_distinct_agents(client):
    r = client.get("/agents/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"proposer", "synthesizer"}
    assert body["proposer"]["total_runs"] == 1
    assert body["synthesizer"]["latest"]["summary"] == "8 trends"


def test_agents_runs_default_limit(client):
    r = client.get("/agents/runs?limit=5")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2  # both seeded runs
    assert {row["agent_id"] for row in rows} == {"proposer", "synthesizer"}


def test_ideas_list_returns_seeded(client):
    r = client.get("/ideas")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["idea_text"] == "A focused idea"
    assert rows[0]["evaluator_verdict"] == "needs_work"


def test_ideas_show_full_returns_critiques(client):
    r = client.get("/ideas/1")
    assert r.status_code == 200
    body = r.json()
    assert body["idea_text"] == "A focused idea"
    assert body["proposer_detail"]["wedge"] == "indie devs"
    assert body["persona_critiques"]["paul_graham"]["subscore"] == 72


def test_ideas_show_404_for_missing(client):
    r = client.get("/ideas/999")
    assert r.status_code == 404


def test_trends_returns_active(client):
    r = client.get("/trends")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["cluster_label"] == "Local LLM inference"
    assert rows[0]["momentum"] == "rising_fast"
    assert rows[0]["member_count"] == 3


def test_intel_recent_excludes_corpus(client):
    """The intel feed must filter out founder_brain + failure_corpus rows
    so the user sees real news, not the static reference corpora."""
    # Add a founder_brain row that should NOT appear in /intel
    from ai_intel.db.session import get_engine
    eng = get_engine(Path(os.environ["JARVIS_DB_PATH"]))
    now = datetime.now(timezone.utc)
    with Session(eng) as s:
        s.add(Item(
            source="founder_brain", url="https://example.test/pg",
            url_hash="pgxyz", title="Schlep blindness",
            body="essay", published_at=now, collected_at=now,
        ))
        s.commit()
    r = client.get("/intel")
    assert r.status_code == 200
    titles = [row["title"] for row in r.json()]
    assert "Test story" in titles
    assert "Schlep blindness" not in titles


# ─── Event bus tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_event_bus_fanout_to_multiple_subscribers():
    """A single publish() must hand the event to every active subscriber."""
    reset_event_bus()
    bus = get_event_bus()
    q1 = await bus.subscribe()
    q2 = await bus.subscribe()
    bus.publish(FleetEvent(type="agent_started", agent_id="x", run_id=1))
    e1 = await asyncio.wait_for(q1.get(), timeout=0.5)
    e2 = await asyncio.wait_for(q2.get(), timeout=0.5)
    assert e1.agent_id == "x"
    assert e2.agent_id == "x"
    await bus.unsubscribe(q1)
    await bus.unsubscribe(q2)


@pytest.mark.asyncio
async def test_event_bus_drops_for_slow_subscriber_not_globally():
    """If one subscriber's queue fills, OTHER subscribers still receive.

    We use a tiny queue_maxsize=1 and drain `fast` between publishes;
    `slow` never drains so its queue stays full and drops the second
    event. fast must still receive both because we made room in time.
    """
    reset_event_bus()
    bus = EventBus(queue_maxsize=1)
    slow = await bus.subscribe()
    fast = await bus.subscribe()
    bus.publish(FleetEvent(type="agent_started", agent_id="x", run_id=1))
    # Drain fast between publishes — emulates a fast consumer
    e1 = await asyncio.wait_for(fast.get(), timeout=0.5)
    assert e1.type == "agent_started"
    # Second publish: slow's queue is still full (it never drained) so
    # publish drops it for slow. fast has room → accepts.
    bus.publish(FleetEvent(type="agent_finished", agent_id="x", run_id=1))
    e2 = await asyncio.wait_for(fast.get(), timeout=0.5)
    assert e2.type == "agent_finished"
    # slow only received the first event
    only = await asyncio.wait_for(slow.get(), timeout=0.5)
    assert only.type == "agent_started"
    assert slow.empty()


# ─── @agent decorator publishes events ──────────────────────────────


@pytest.mark.asyncio
async def test_decorator_publishes_start_and_finish_events(db_path):
    """When an @agent-decorated coroutine runs, the bus must see two
    events with matching run_id: agent_started THEN agent_finished."""
    reset_event_bus()
    from ai_intel.agents.decorator import agent as agent_decorator
    from ai_intel.db.session import get_engine

    eng = get_engine(Path(os.environ["JARVIS_DB_PATH"]))
    bus = get_event_bus()
    received: list[FleetEvent] = []
    q = await bus.subscribe()

    async def drain():
        # Read two events with a deadline
        for _ in range(2):
            evt = await asyncio.wait_for(q.get(), timeout=2.0)
            received.append(evt)

    @agent_decorator("test_agent")
    async def fake_agent(engine, **kwargs):
        return {"summary": "test ran"}

    drainer = asyncio.create_task(drain())
    await fake_agent(eng)
    await drainer

    assert len(received) == 2
    assert received[0].type == "agent_started"
    assert received[1].type == "agent_finished"
    assert received[0].agent_id == "test_agent"
    assert received[1].agent_id == "test_agent"
    assert received[0].run_id == received[1].run_id
    assert received[1].summary == "test ran"
    await bus.unsubscribe(q)


# ─── Tool registry tests ────────────────────────────────────────────


def test_tool_registry_shape():
    """Every Tool has a non-empty name + description + valid schema."""
    from ai_intel.brain.tools import build_registry, anthropic_tool_specs
    reg = build_registry()
    assert "agents.status" in reg
    assert "ideas.list" in reg
    assert "memory.recall" in reg
    for name, tool in reg.items():
        assert tool.name == name
        assert tool.description.strip(), f"{name} missing description"
        assert isinstance(tool.input_schema, dict)
        assert tool.input_schema.get("type") == "object"
    specs = anthropic_tool_specs(reg)
    assert all("name" in s and "description" in s and "input_schema" in s for s in specs)


@pytest.mark.asyncio
async def test_invoke_executes_allowed_tool(client):
    """An allowed tool runs its handler and returns the result dict."""
    from ai_intel.brain.tools import build_registry, invoke
    from ai_intel.db.session import get_engine
    eng = get_engine(Path(os.environ["JARVIS_DB_PATH"]))
    reg = build_registry()
    out = await invoke(reg, eng, "ideas.list", {"status": "needs_work"})
    assert "ideas" in out
    assert len(out["ideas"]) >= 1
    assert out["ideas"][0]["evaluator_verdict"] == "needs_work"


@pytest.mark.asyncio
async def test_invoke_refuses_denied_tool(tmp_path, monkeypatch):
    """A denied tool queues an approval and returns refused payload,
    NEVER invoking the handler."""
    from ai_intel.brain.tools import Tool, invoke
    # Point the approval queue at a temp file
    qp = tmp_path / "approvals.queue"
    monkeypatch.setattr(
        "ai_intel.jarvis.permissions.APPROVAL_QUEUE_PATH", qp,
    )
    # Force the policy to deny our test tool — create a user policy file
    user_cfg = tmp_path / "tools.toml"
    user_cfg.write_text('"test.dangerous" = "deny"\n', encoding="utf-8")
    monkeypatch.setattr(
        "ai_intel.jarvis.permissions.USER_CONFIG_PATH", user_cfg,
    )
    called = {"n": 0}
    async def handler(engine, **kw):
        called["n"] += 1
        return {"would_run": True}
    reg = {
        "test.dangerous": Tool(
            name="test.dangerous", description="don't",
            input_schema={"type": "object", "properties": {}},
            handler=handler,
        ),
    }
    out = await invoke(reg, None, "test.dangerous", {})
    assert "refused" in out
    assert "approval_id" in out
    assert called["n"] == 0
    # Approval queue must contain the entry
    assert qp.exists()
    lines = [l for l in qp.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["tool"] == "test.dangerous"
    assert entry["status"] == "pending"


@pytest.mark.asyncio
async def test_invoke_returns_error_for_unknown_tool():
    from ai_intel.brain.tools import invoke
    out = await invoke({}, None, "nonexistent.tool", {})
    assert "error" in out
    assert "unknown" in out["error"].lower()
