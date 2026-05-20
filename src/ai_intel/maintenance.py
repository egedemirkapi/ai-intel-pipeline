"""Background-maintenance utilities for the local SQLite DB.

These prune slow-growing audit tables that aren't actionable past a
certain age. Designed to run daily; safe to call ad-hoc.

Tables managed:
    AgentRun              — every @agent invocation records a row.
                            Completed/failed rows older than keep_days
                            have nothing actionable; we delete them.
    SaturationAssessment  — 7-day TTL on `expires_at`. Past expiry +
                            grace_days, the row is just dead weight.

Why this exists: in a 24/7 cloud deploy these tables grow unbounded.
The audit identified this as an operational landmine. Pruning is
data-safe (only deletes rows that no live code path can possibly read).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, delete, select

from ai_intel.db.models import AgentRun, SaturationAssessment

logger = logging.getLogger(__name__)


def prune_old_agent_runs(engine, *, keep_days: int = 30) -> int:
    """Delete completed/failed AgentRun rows older than ``keep_days``.

    Returns the number of rows removed. Pending/running rows are
    preserved regardless of age — those represent in-flight work.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    with Session(engine) as s:
        # Use a select-then-delete pattern so we can log the count
        # and dodge SQLAlchemy dialect differences in bulk delete.
        rows = list(s.exec(
            select(AgentRun)
            .where(AgentRun.started_at < cutoff)
            .where(AgentRun.status.in_(("completed", "failed")))
        ))
        if not rows:
            return 0
        for r in rows:
            s.delete(r)
        s.commit()
    n = len(rows)
    logger.info("maintenance: pruned %d AgentRun rows older than %d days", n, keep_days)
    return n


def prune_stale_saturation(engine, *, grace_days: int = 30) -> int:
    """Delete SaturationAssessment rows whose ``expires_at`` was more
    than ``grace_days`` ago. The cache TTL is enforced at read-time, so
    these rows are unreachable by the saturator; we drop them.

    Returns the number of rows removed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=grace_days)
    with Session(engine) as s:
        rows = list(s.exec(
            select(SaturationAssessment)
            .where(SaturationAssessment.expires_at < cutoff)
        ))
        if not rows:
            return 0
        for r in rows:
            s.delete(r)
        s.commit()
    n = len(rows)
    logger.info(
        "maintenance: pruned %d SaturationAssessment rows whose expiry "
        "was over %d days ago", n, grace_days,
    )
    return n


def run_daily_maintenance(engine) -> dict[str, int]:
    """One-shot daily cleanup. Returns a summary dict for logging/CLI."""
    return {
        "agent_runs_pruned": prune_old_agent_runs(engine),
        "saturation_pruned": prune_stale_saturation(engine),
    }
