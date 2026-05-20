"""Print full proposer-reasoning chain for one or more IdeaCandidate ids."""
import json
import sys
from pathlib import Path

from sqlmodel import Session

from ai_intel.db.models import IdeaCandidate
from ai_intel.db.session import get_engine


def main():
    ids = [int(x) for x in sys.argv[1:]]
    if not ids:
        print("usage: python scripts/diag_idea_detail.py <id> [<id> ...]")
        return
    engine = get_engine(Path("data/items.db"))
    with Session(engine) as s:
        for cid in ids:
            r = s.get(IdeaCandidate, cid)
            if r is None:
                print(f"#{cid}: not found")
                continue
            try:
                blob = json.loads(r.persona_critiques_json or "{}")
            except json.JSONDecodeError:
                blob = {}
            d = blob.get("_proposer_detail", {})
            print(f"\n=== #{cid} ({r.evaluator_verdict}, mean={r.evaluator_score}) ===")
            print(f"IDEA: {r.idea_text}\n")
            for label, key in (
                ("trend_label",    "trend_label"),
                ("momentum",       "trend_momentum"),
                ("pattern",        "pattern_recognized"),
                ("gap",            "gap_identified"),
                ("avoids",         "failure_pattern_avoided"),
                ("wedge",          "wedge"),
                ("validation",     "validation_step"),
                ("why_now",        "why_now"),
                ("differentiation","differentiation"),
            ):
                val = d.get(key)
                if val:
                    print(f"  {label:16s} {val}")


if __name__ == "__main__":
    main()
