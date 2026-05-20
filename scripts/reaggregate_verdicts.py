"""Re-apply _aggregate() to every IdeaCandidate using existing critique data.

Useful after changing aggregation rules (e.g. adding the borderline tier)
without needing to re-run the LLM evaluator. Reads persona_critiques_json,
recomputes (score, verdict), writes back if changed. No LLM calls, no cost.
"""
import json
from pathlib import Path

from sqlmodel import Session, select

from ai_intel.agents.evaluator import _aggregate
from ai_intel.db.models import IdeaCandidate
from ai_intel.db.session import get_engine


def main():
    engine = get_engine(Path("data/items.db"))
    changed = 0
    with Session(engine) as s:
        rows = list(s.exec(
            select(IdeaCandidate)
            .where(IdeaCandidate.persona_critiques_json.is_not(None))
            .where(IdeaCandidate.evaluator_score > 0)
        ))
        for cand in rows:
            try:
                blob = json.loads(cand.persona_critiques_json or "{}")
            except json.JSONDecodeError:
                continue
            crits = {
                pid: v for pid, v in blob.items()
                if pid != "_proposer_detail"
                and isinstance(v, dict)
                and "subscore" in v
            }
            if not crits:
                continue
            score, verdict, _min_sub, _vetoer = _aggregate(crits)
            if verdict != cand.evaluator_verdict or score != cand.evaluator_score:
                print(
                    f"#{cand.id}: "
                    f"{cand.evaluator_verdict}({cand.evaluator_score}) "
                    f"-> {verdict}({score})"
                )
                cand.evaluator_verdict = verdict
                cand.status = verdict
                cand.evaluator_score = score
                s.add(cand)
                changed += 1
        s.commit()
    print(f"\nreclassified {changed} candidates")


if __name__ == "__main__":
    main()
