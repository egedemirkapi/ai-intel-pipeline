"""Read-only views over AgentRun for ``jarvis agents status`` etc."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, desc, select

from ai_intel.db.models import AgentRun


def recent_runs(
    engine,
    *,
    agent_id: str | None = None,
    limit: int = 20,
) -> list[AgentRun]:
    """Most-recent-first list of AgentRun rows."""
    with Session(engine) as s:
        q = select(AgentRun).order_by(desc(AgentRun.started_at))
        if agent_id:
            q = q.where(AgentRun.agent_id == agent_id)
        return list(s.exec(q.limit(limit)))


def last_completed(engine, agent_id: str) -> AgentRun | None:
    """The most recent completed run of a given agent."""
    with Session(engine) as s:
        q = (
            select(AgentRun)
            .where(AgentRun.agent_id == agent_id)
            .where(AgentRun.status == "completed")
            .order_by(desc(AgentRun.finished_at))
            .limit(1)
        )
        return s.exec(q).first()


def summary_for_user(engine, window_hours: int = 24) -> str:
    """Multi-line human-readable rollup for Telegram / CLI.

    Example:
        collector  green   14 runs / 24h  last 03:12 UTC
        saturator  green    1 run  / 24h  last 03:00 UTC
        proposer   idle     0 runs/ 24h   last —
        evaluator  red      1 run failed at 14:02 UTC: ...
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    with Session(engine) as s:
        runs = list(s.exec(
            select(AgentRun).where(AgentRun.started_at >= cutoff)
        ))
    by_agent: dict[str, list[AgentRun]] = {}
    for r in runs:
        by_agent.setdefault(r.agent_id, []).append(r)

    if not by_agent:
        return "(no agent activity in the last %dh)" % window_hours

    lines: list[str] = []
    for agent_id in sorted(by_agent):
        rows = sorted(by_agent[agent_id], key=lambda r: r.started_at, reverse=True)
        n = len(rows)
        failed = [r for r in rows if r.status == "failed"]
        completed = [r for r in rows if r.status == "completed"]
        last = rows[0]
        status_label = (
            "red" if failed and not completed
            else "yellow" if failed
            else "green"
            if completed
            else "running"
        )
        last_at = last.finished_at or last.started_at
        suffix = ""
        if failed:
            tail = (failed[0].error or "").splitlines()[0][:80]
            suffix = f"  last_fail: {tail}"
        lines.append(
            f"{agent_id:<14} {status_label:<7} "
            f"{n:>2} runs / {window_hours}h  "
            f"last {last_at.strftime('%H:%M UTC')}  status={last.status}{suffix}"
        )
    return "\n".join(lines)
