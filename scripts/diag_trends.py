"""Show recent TrendSynthesis rows with full reasoning chain."""
import json
from pathlib import Path

from sqlmodel import Session, desc, select

from ai_intel.db.models import TrendSynthesis
from ai_intel.db.session import get_engine


def main():
    eng = get_engine(Path("data/items.db"))
    with Session(eng) as s:
        rows = list(s.exec(
            select(TrendSynthesis)
            .where(TrendSynthesis.status == "active")
            .order_by(desc(TrendSynthesis.generated_at))
        ))
    if not rows:
        print("(no active trend syntheses)")
        return
    print(f"=== {len(rows)} active trends (generated {rows[0].generated_at}) ===\n")
    for r in rows:
        members = json.loads(r.member_item_ids_json or "[]")
        convergence = json.loads(r.convergence_with_json or "[]")
        print(f"▸ {r.cluster_label}   [{r.momentum}]")
        print(f"   shift:      {r.underlying_shift}")
        print(f"   capability: {r.new_capability}")
        print(f"   members:    {len(members)} items")
        if convergence:
            print(f"   converges:  " + ", ".join(convergence))
        print()


if __name__ == "__main__":
    main()
