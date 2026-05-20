"""Show per-persona subscore breakdown for given candidate IDs."""
import json
import sys
from pathlib import Path

from sqlmodel import Session, select

from ai_intel.db.models import IdeaCandidate
from ai_intel.db.session import get_engine


def main():
    ids = [int(x) for x in sys.argv[1:]] or [11, 12, 13]
    engine = get_engine(Path("data/items.db"))
    with Session(engine) as s:
        rows = list(s.exec(select(IdeaCandidate).where(IdeaCandidate.id.in_(ids))))

    for r in sorted(rows, key=lambda x: x.id or 0):
        print(f"\n#{r.id} mean={r.evaluator_score} verdict={r.evaluator_verdict}")
        try:
            blob = json.loads(r.persona_critiques_json or "{}")
        except json.JSONDecodeError:
            print("  (unparseable)")
            continue
        for pid, c in blob.items():
            if pid == "_proposer_detail" or not isinstance(c, dict):
                continue
            sub = c.get("subscore", "?")
            crit = (c.get("critique") or "")[:90]
            print(f"  {pid:14s} {sub!s:>4}  {crit}")


if __name__ == "__main__":
    main()
