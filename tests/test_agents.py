"""Tests for the Phase 7 agent fleet runtime."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from ai_intel.agents import (
    agent,
    call_llm,
    estimate_cost_usd,
    last_completed,
    recent_runs,
    summary_for_user,
)
from ai_intel.agents import runtime as RT
from ai_intel.db.models import AgentRun


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------


def test_cost_haiku():
    # 1k input + 1k output at Haiku price
    cost = estimate_cost_usd("claude-haiku-4-5", 1000, 1000)
    # (1k/1M)*$1 + (1k/1M)*$5 = $0.001 + $0.005 = $0.006
    assert abs(cost - 0.006) < 1e-9


def test_cost_sonnet():
    cost = estimate_cost_usd("claude-sonnet-4-6", 1000, 1000)
    # $3 + $15 per M → $0.003 + $0.015 = $0.018
    assert abs(cost - 0.018) < 1e-9


def test_cost_unknown_model_uses_default():
    cost = estimate_cost_usd("some-unknown-model", 1000, 1000)
    # Default to Haiku pricing
    assert abs(cost - 0.006) < 1e-9


# ---------------------------------------------------------------------------
# LLM router — bridge reachability + fallback
# ---------------------------------------------------------------------------


def test_bridge_unreachable_falls_back_to_api(monkeypatch):
    """If prefer='oauth' but bridge is down, we must use api_key path."""
    # Force "not reachable" without making real HTTP calls
    monkeypatch.setattr(RT, "_is_bridge_reachable", lambda url, **kw: False)

    called = {}

    def fake_api(messages, *, model, max_tokens, temperature):
        called["model"] = model
        called["messages"] = messages
        from ai_intel.agents.runtime import LLMResponse
        return LLMResponse(
            text="hello from api",
            prompt_tokens=10,
            completion_tokens=5,
            auth_mode="api_key",
            model=model,
            cost_usd=estimate_cost_usd(model, 10, 5),
        )

    monkeypatch.setattr(RT, "_call_api_key", fake_api)

    resp = call_llm(
        [{"role": "user", "content": "hi"}],
        prefer="oauth",
        model="claude-haiku-4-5",
        bridge_url="http://nope:9999/jask",
    )
    assert resp.auth_mode == "api_key"
    assert resp.text == "hello from api"
    assert called["model"] == "claude-haiku-4-5"


def test_bridge_reachable_uses_oauth(monkeypatch):
    monkeypatch.setattr(RT, "_is_bridge_reachable", lambda url, **kw: True)

    def fake_bridge(bridge_url, messages, **kw):
        from ai_intel.agents.runtime import LLMResponse
        return LLMResponse(
            text="hello from oauth",
            prompt_tokens=11,
            completion_tokens=7,
            auth_mode="oauth",
            model="claude-via-oauth",
            cost_usd=0.0,
        )

    monkeypatch.setattr(RT, "_call_oauth_bridge", fake_bridge)

    resp = call_llm(
        [{"role": "user", "content": "hi"}],
        prefer="oauth",
        bridge_url="http://localhost:9999/jask",
    )
    assert resp.auth_mode == "oauth"
    assert resp.cost_usd == 0.0


def test_prefer_api_key_skips_bridge(monkeypatch):
    """prefer='api_key' must NOT probe the bridge at all."""
    probed = {"called": False}

    def fake_probe(*a, **kw):
        probed["called"] = True
        return True
    monkeypatch.setattr(RT, "_is_bridge_reachable", fake_probe)

    def fake_api(messages, *, model, max_tokens, temperature):
        from ai_intel.agents.runtime import LLMResponse
        return LLMResponse(
            text="x",
            prompt_tokens=1,
            completion_tokens=1,
            auth_mode="api_key",
            model=model,
            cost_usd=0.0,
        )
    monkeypatch.setattr(RT, "_call_api_key", fake_api)

    call_llm([{"role": "user", "content": "hi"}], prefer="api_key")
    assert probed["called"] is False


# ---------------------------------------------------------------------------
# @agent decorator
# ---------------------------------------------------------------------------


def test_agent_decorator_records_completion(engine):
    @agent("test_completed")
    async def the_agent(engine, **_):
        return {
            "summary": "did the thing",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "cost_usd": 0.001,
            "auth_mode": "oauth",
        }

    result = asyncio.run(the_agent(engine))
    assert result["summary"] == "did the thing"

    with Session(engine) as s:
        rows = s.exec(select(AgentRun)).all()
    assert len(rows) == 1
    r = rows[0]
    assert r.agent_id == "test_completed"
    assert r.status == "completed"
    assert r.summary == "did the thing"
    assert r.prompt_tokens == 100
    assert r.completion_tokens == 50
    assert r.cost_estimate_usd == pytest.approx(0.001)
    assert r.auth_mode == "oauth"
    assert r.finished_at is not None
    assert r.error is None


def test_agent_decorator_captures_failure(engine):
    @agent("test_failed")
    async def crashy(engine, **_):
        raise ValueError("kaboom")

    with pytest.raises(ValueError):
        asyncio.run(crashy(engine))

    with Session(engine) as s:
        r = s.exec(select(AgentRun)).first()
    assert r is not None
    assert r.status == "failed"
    assert "kaboom" in (r.error or "")
    assert r.finished_at is not None


def test_agent_decorator_handles_none_return(engine):
    @agent("test_none")
    async def no_return(engine, **_):
        return None

    asyncio.run(no_return(engine))

    with Session(engine) as s:
        r = s.exec(select(AgentRun)).first()
    assert r is not None
    assert r.status == "completed"
    assert r.summary is None
    assert r.cost_estimate_usd == 0.0


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------


def _seed_run(
    engine,
    *,
    agent_id: str,
    status: str,
    when: datetime,
    error: str | None = None,
) -> None:
    with Session(engine) as s:
        s.add(AgentRun(
            agent_id=agent_id,
            status=status,
            started_at=when,
            finished_at=when + timedelta(seconds=1),
            error=error,
        ))
        s.commit()


def test_recent_runs_orders_newest_first(engine):
    now = datetime.now(timezone.utc)
    _seed_run(engine, agent_id="A", status="completed", when=now - timedelta(hours=2))
    _seed_run(engine, agent_id="A", status="completed", when=now - timedelta(hours=1))
    _seed_run(engine, agent_id="B", status="completed", when=now - timedelta(hours=3))

    rows = recent_runs(engine, limit=10)
    assert len(rows) == 3
    assert rows[0].agent_id == "A"  # newest
    assert rows[1].agent_id == "A"
    assert rows[2].agent_id == "B"  # oldest


def test_recent_runs_filters_by_agent(engine):
    now = datetime.now(timezone.utc)
    _seed_run(engine, agent_id="A", status="completed", when=now - timedelta(hours=1))
    _seed_run(engine, agent_id="B", status="completed", when=now - timedelta(hours=2))
    rows = recent_runs(engine, agent_id="A")
    assert len(rows) == 1
    assert rows[0].agent_id == "A"


def test_last_completed_ignores_failures(engine):
    now = datetime.now(timezone.utc)
    _seed_run(engine, agent_id="X", status="failed", when=now - timedelta(minutes=10), error="bad")
    _seed_run(engine, agent_id="X", status="completed", when=now - timedelta(hours=1))

    last = last_completed(engine, "X")
    assert last is not None
    assert last.status == "completed"


def test_summary_for_user_classifies_status(engine):
    now = datetime.now(timezone.utc)
    _seed_run(engine, agent_id="all_good", status="completed", when=now - timedelta(minutes=5))
    _seed_run(engine, agent_id="some_fail", status="completed", when=now - timedelta(minutes=10))
    _seed_run(engine, agent_id="some_fail", status="failed", when=now - timedelta(minutes=2), error="bad thing")
    _seed_run(engine, agent_id="all_fail", status="failed", when=now - timedelta(minutes=15), error="all bad")

    text = summary_for_user(engine, window_hours=24)
    # green for fully-completed, yellow for mixed, red for fully-failed
    assert "all_good" in text and "green" in text
    assert "some_fail" in text and "yellow" in text
    assert "all_fail" in text and "red" in text


def test_summary_for_user_empty_state(engine):
    out = summary_for_user(engine, window_hours=1)
    assert "no agent activity" in out
