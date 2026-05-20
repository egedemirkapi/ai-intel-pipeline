"""Tests for src/ai_intel/maintenance.py — pruning audit tables.

Verifies that:
- Old completed/failed AgentRun rows are removed (data-safe deletion)
- Pending/running rows are preserved regardless of age
- SaturationAssessment rows past expiry+grace_days are removed
- Rows still within expiry are preserved
- The one-shot ``run_daily_maintenance`` returns the prune counts
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from ai_intel.db.models import AgentRun, SaturationAssessment
from ai_intel.maintenance import (
    prune_old_agent_runs,
    prune_stale_saturation,
    run_daily_maintenance,
)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


def _seed_run(engine, *, agent_id: str, status: str, age_days: int) -> int:
    """Seed an AgentRun ``age_days`` days in the past, return its id."""
    started = datetime.now(timezone.utc) - timedelta(days=age_days)
    with Session(engine) as s:
        r = AgentRun(agent_id=agent_id, status=status, started_at=started)
        s.add(r)
        s.commit()
        s.refresh(r)
        return r.id


def _seed_saturation(engine, *, topic: str, expires_in_days: int) -> int:
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        row = SaturationAssessment(
            topic=topic,
            score=0.3,
            competitor_count=2,
            assessed_at=now - timedelta(days=7),
            expires_at=now + timedelta(days=expires_in_days),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def test_prune_old_agent_runs_removes_old_completed(engine):
    fresh = _seed_run(engine, agent_id="proposer", status="completed", age_days=5)
    stale = _seed_run(engine, agent_id="proposer", status="completed", age_days=45)
    deleted = prune_old_agent_runs(engine, keep_days=30)
    assert deleted == 1
    with Session(engine) as s:
        rows = list(s.exec(select(AgentRun)))
    remaining_ids = {r.id for r in rows}
    assert fresh in remaining_ids
    assert stale not in remaining_ids


def test_prune_old_agent_runs_preserves_running(engine):
    """Pending and running rows must NOT be deleted regardless of age."""
    pending_old = _seed_run(engine, agent_id="proposer", status="pending", age_days=60)
    running_old = _seed_run(engine, agent_id="proposer", status="running", age_days=60)
    deleted = prune_old_agent_runs(engine, keep_days=30)
    assert deleted == 0
    with Session(engine) as s:
        rows = list(s.exec(select(AgentRun)))
    assert {r.id for r in rows} == {pending_old, running_old}


def test_prune_old_agent_runs_handles_empty(engine):
    """No rows in DB → returns 0 without raising."""
    assert prune_old_agent_runs(engine) == 0


def test_prune_stale_saturation_removes_old_expiries(engine):
    """A row whose expires_at is more than grace_days ago is dropped."""
    # Build a row whose expires_at is 45 days in the PAST → past grace=30
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add(SaturationAssessment(
            topic="dead-topic",
            score=0.4,
            competitor_count=1,
            assessed_at=now - timedelta(days=60),
            expires_at=now - timedelta(days=45),
        ))
        s.commit()
    # And one that's still alive
    alive_id = _seed_saturation(engine, topic="alive-topic", expires_in_days=3)
    deleted = prune_stale_saturation(engine, grace_days=30)
    assert deleted == 1
    with Session(engine) as s:
        topics = {r.topic for r in s.exec(select(SaturationAssessment))}
    assert "dead-topic" not in topics
    assert "alive-topic" in topics


def test_run_daily_maintenance_returns_counts(engine):
    """The orchestrator returns per-table prune counts."""
    _seed_run(engine, agent_id="proposer", status="completed", age_days=45)
    _seed_run(engine, agent_id="evaluator", status="failed", age_days=45)
    summary = run_daily_maintenance(engine)
    assert summary["agent_runs_pruned"] == 2
    assert summary["saturation_pruned"] == 0
