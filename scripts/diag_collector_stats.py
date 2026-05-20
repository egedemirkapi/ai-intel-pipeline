"""Show collector cadence + intel volume stats — for the 'is this live 24/7?' question."""
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlmodel import Session, select, func, desc

from ai_intel.db.models import Item, AgentRun
from ai_intel.db.session import get_engine


def main():
    eng = get_engine(Path("data/items.db"))
    s = Session(eng)
    now = datetime.now(timezone.utc)

    intel_filter = Item.source.not_in(("founder_brain", "failure_corpus"))

    total = s.exec(select(func.count(Item.id))).first()
    intel_total = s.exec(select(func.count(Item.id)).where(intel_filter)).first()
    earliest = s.exec(select(func.min(Item.collected_at)).where(intel_filter)).first()
    last_24h = s.exec(
        select(func.count(Item.id))
        .where(Item.collected_at >= now - timedelta(days=1))
        .where(intel_filter)
    ).first()
    last_2h = s.exec(
        select(func.count(Item.id))
        .where(Item.collected_at >= now - timedelta(hours=2))
        .where(intel_filter)
    ).first()

    print(f"TOTAL items: {total}")
    print(f"INTEL (excluding founder + failure corpus): {intel_total}")
    if earliest:
        ea = earliest if earliest.tzinfo else earliest.replace(tzinfo=timezone.utc)
        span_days = (now - ea).total_seconds() / 86400.0
        print(f"Earliest intel collected_at: {ea}  ({span_days:.2f} days ago)")
    print(f"Last 24 hours: {last_24h} new intel items")
    print(f"Last 2 hours:  {last_2h} new intel items")
    print()
    print("Recent collector runs (last 10):")
    runs = list(s.exec(
        select(AgentRun)
        .where(AgentRun.agent_id == "collector")
        .order_by(desc(AgentRun.started_at))
        .limit(10)
    ))
    if not runs:
        print("  (zero 'collector' runs recorded in AgentRun)")
        print("  The collector is wired via apscheduler but NOT running as a daemon")
        print("  on this Windows box — it only runs when you invoke the pipeline.")
    else:
        for r in runs:
            summary = (r.summary or "")[:70]
            print(f"  {r.started_at}  {r.status:10s}  {summary}")
    print()
    print("Per-source breakdown (intel only, last 24h):")
    rows = list(s.exec(
        select(Item.source, func.count(Item.id))
        .where(Item.collected_at >= now - timedelta(days=1))
        .where(intel_filter)
        .group_by(Item.source)
        .order_by(desc(func.count(Item.id)))
    ))
    for src, n in rows:
        print(f"  {src:30s} {n}")


if __name__ == "__main__":
    main()
