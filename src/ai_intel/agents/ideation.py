"""weekly_ideation orchestrator — the coordinated heartbeat.

Single function that chains proposer → evaluator across N candidates,
then returns a summary. This is the heartbeat the scheduler should call
weekly. Until cloud deploy lands, it's also what `jarvis ideate` calls
for an on-demand run.

The proposer already gates on saturation internally (it asks the
saturator before drafting), and the evaluator hard-kills on dissent
(min(persona_subscores) < 55). So this orchestrator stays lean —
just loops + summary, no extra gating logic.
"""
from __future__ import annotations

import json
import logging

from sqlmodel import Session, desc, select

from ai_intel.agents.decorator import agent
from ai_intel.agents.evaluator import evaluator
from ai_intel.agents.proposer import proposer
from ai_intel.db.models import IdeaCandidate
from ai_intel.personas import KNOWN_PERSONAS

logger = logging.getLogger(__name__)


@agent("weekly_ideation")
async def weekly_ideation(
    engine,
    *,
    n_candidates: int = 5,
    rotate_personas: bool = True,
    proposer_model: str = "claude-haiku-4-5",
    evaluator_model: str = "claude-haiku-4-5",
):
    """Run a full ideation cycle.

    1. Draft up to ``n_candidates`` IdeaCandidate rows via the proposer.
       Each call rotates through the founder personas so we don't get
       stuck looking at the world from one lens.
    2. Run the evaluator over every freshly-proposed candidate.
    3. Return a summary listing escalated / needs_work / killed counts.

    The proposer skips saturated topics internally; the evaluator
    kills on persona dissent. So calling this is the whole loop.
    """
    proposed_ids: list[int] = []
    proposer_skips = 0

    personas = list(KNOWN_PERSONAS)

    for i in range(n_candidates):
        pid = personas[i % len(personas)] if rotate_personas else "paul_graham"
        try:
            result = await proposer(
                engine,
                persona_id=pid,
                model=proposer_model,
            )
        except Exception as exc:
            logger.warning("ideation: proposer raised: %s", exc)
            proposer_skips += 1
            continue
        # Pull the candidate id from the result pointer if present
        ptr = result.get("output_pointer") if result else None
        if ptr:
            try:
                proposed_ids.append(json.loads(ptr).get("idea_candidate_id"))
            except (json.JSONDecodeError, AttributeError):
                pass
        else:
            proposer_skips += 1

    proposed_ids = [i for i in proposed_ids if i is not None]

    if not proposed_ids:
        return {
            "summary": (
                f"no ideas proposed in this cycle "
                f"(attempted {n_candidates}, skipped {proposer_skips} — "
                f"likely all candidates were saturated or no fresh tech signal)"
            ),
            "auth_mode": "api_key",
        }

    # Evaluate everything we just proposed
    eval_result = await evaluator(
        engine,
        batch_limit=len(proposed_ids),
        model=evaluator_model,
    )

    # Final breakdown
    with Session(engine) as s:
        rows = list(s.exec(
            select(IdeaCandidate)
            .where(IdeaCandidate.id.in_(proposed_ids))
            .order_by(desc(IdeaCandidate.evaluator_score).nullslast())
        ))

    by_status: dict[str, list[int]] = {}
    for r in rows:
        by_status.setdefault(r.status, []).append(r.id)

    parts = [f"proposed={len(proposed_ids)}"]
    for status in ("escalated", "needs_work", "killed", "proposed"):
        if status in by_status:
            parts.append(f"{status}={len(by_status[status])}")

    escalated_ids = by_status.get("escalated", [])
    if escalated_ids:
        parts.append(f"survivors={escalated_ids}")

    return {
        "summary": " · ".join(parts),
        "prompt_tokens": eval_result.get("prompt_tokens", 0) if eval_result else 0,
        "completion_tokens": eval_result.get("completion_tokens", 0) if eval_result else 0,
        "cost_usd": eval_result.get("cost_usd", 0.0) if eval_result else 0.0,
        "auth_mode": eval_result.get("auth_mode") if eval_result else None,
        "output_pointer": json.dumps({
            "proposed_ids": proposed_ids,
            "by_status": {k: list(v) for k, v in by_status.items()},
        }),
    }
