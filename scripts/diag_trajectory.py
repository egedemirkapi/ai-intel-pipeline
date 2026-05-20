"""Print the top rising-star entities + the items the new picker would
return. Read-only — no LLM calls, costs nothing.

Usage:
    python scripts/diag_trajectory.py
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlmodel import Session, select

from ai_intel.agents.proposer import _entity_count_map, _extract_entities
from ai_intel.db.models import Item
from ai_intel.db.session import get_engine


def main():
    engine = get_engine(Path("data/items.db"))
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=7)
    baseline_start = now - timedelta(days=60)

    recent = _entity_count_map(engine, since=recent_start)
    baseline = _entity_count_map(engine, since=baseline_start, before=recent_start)
    historical = _entity_count_map(engine, before=baseline_start)

    print(f"recent (7d) entities: {len(recent)}")
    print(f"baseline (7-60d) entities: {len(baseline)}")
    print(f"historical (>60d) entities: {len(historical)}")
    print()

    has_history = bool(baseline) or bool(historical)
    max_recent = max(recent.values()) if recent else 0
    tail_upper = max(5, int(max_recent * 0.15))
    mode = "TRAJECTORY (history available)" if has_history else f"COLD-START (rising tail 3-{tail_upper})"
    print(f"picker mode: {mode}")
    print()

    scored = []
    for e, r in recent.items():
        b = baseline.get(e, 0)
        h = historical.get(e, 0)
        if has_history:
            novelty = 1.0 / (1.0 + h / 10.0)
            momentum = r / (1.0 + b)
            score = novelty * momentum * r
        else:
            if r < 3 or r > tail_upper:
                continue
            novelty = 0.0
            momentum = 0.0
            score = float(r)
        scored.append((score, e, r, b, h, novelty, momentum))
    scored.sort(reverse=True)

    print(f"{'score':>8}  {'recent':>6}  {'base':>5}  {'hist':>5}  entity")
    print("-" * 80)
    for score, e, r, b, h, n, m in scored[:25]:
        print(f"{score:8.2f}  {r:6d}  {b:5d}  {h:5d}  {e}")

    print("\n--- TOP 10 items by picker score ---\n")
    cutoff = now - timedelta(days=14)
    entity_scores = {e: s for s, e, *_ in scored}
    with Session(engine) as s:
        candidates = list(s.exec(
            select(Item)
            .where(Item.collected_at >= cutoff)
            .where(Item.source != "pain_source")
            .where(Item.source != "founder_brain")
            .where(Item.classification.is_not(None))
            .where(Item.entities_json.is_not(None))
            .limit(300)
        ))
    item_scored = []
    for item in candidates:
        ents = _extract_entities(item)
        score = max(
            (entity_scores.get(e.lower(), 0.0) for e in ents),
            default=0.0,
        )
        if score > 0:
            item_scored.append((score, item))
    item_scored.sort(key=lambda x: -x[0])
    for sc, it in item_scored[:10]:
        ents = ", ".join(_extract_entities(it)[:5])
        print(f"  {sc:7.2f}  [{it.source}] {it.title[:80]}")
        print(f"           ents: {ents}")


if __name__ == "__main__":
    main()
