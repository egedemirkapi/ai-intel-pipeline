"""weekly_ideation orchestrator — the coordinated heartbeat.

Chains proposer → evaluator across N candidates and returns a summary.
This is the heartbeat the scheduler should call weekly. Until cloud
deploy lands, it's also what `jarvis ideate` calls for an on-demand run.

When ``use_synthesis=True`` (the default), each candidate iteration
picks a fresh ``TrendSynthesis`` row and reasons about a META-PATTERN
instead of a single news headline. Falls back gracefully to single-item
mode if no active trends exist.

The proposer already gates on saturation internally; the evaluator
hard-kills on dissent (min subscore < 55, with a borderline carve-out
for mean ≥ 60). This orchestrator stays lean — loops + summary, no
extra gating logic.
"""
from __future__ import annotations

import json
import logging

from sqlmodel import Session, desc, select

from ai_intel.agents.decorator import agent
from ai_intel.agents.evaluator import evaluator
from ai_intel.agents.proposer import _pick_trend, proposer
from ai_intel.db.models import IdeaCandidate
from ai_intel.personas import KNOWN_PERSONAS

logger = logging.getLogger(__name__)


@agent("weekly_ideation")
async def weekly_ideation(
    engine,
    *,
    n_candidates: int = 5,
    rotate_personas: bool = True,
    use_synthesis: bool = True,
    proposer_model: str = "claude-haiku-4-5",
    evaluator_model: str = "claude-haiku-4-5",
):
    """Run a full ideation cycle.

    Args:
        n_candidates:      how many ideas to attempt this cycle
        rotate_personas:   rotate through the founder personas across calls
        use_synthesis:     if True, prefer TrendSynthesis rows as the
                           proposer's input (deliberate ecosystem reasoning).
                           Falls back to single-item mode if no active
                           trends exist. Set False to force single-item
                           mode regardless of trend availability.
        proposer_model:    LLM model id for the proposer call
        evaluator_model:   LLM model id for each persona critic

    Returns AgentResult dict — summary lists escalated / needs_work /
    borderline / killed counts.
    """
    proposed_ids: list[int] = []
    proposer_skips = 0
    trend_calls = 0
    single_item_calls = 0

    personas = list(KNOWN_PERSONAS)

    for i in range(n_candidates):
        pid = personas[i % len(personas)] if rotate_personas else "paul_graham"
        # Pick a fresh trend per iteration so the cycle covers a variety of
        # meta-patterns when many active trends exist.
        trend = _pick_trend(engine) if use_synthesis else None
        if trend is not None:
            trend_calls += 1
        else:
            single_item_calls += 1
        try:
            result = await proposer(
                engine,
                persona_id=pid,
                trend=trend,
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
                f"(attempted {n_candidates}, skipped {proposer_skips}; "
                f"trend_mode={trend_calls} single_item_mode={single_item_calls} — "
                f"likely all candidates were saturated or no fresh tech signal)"
            ),
            "auth_mode": "api_key",
        }

    # Evaluate exactly the candidates we just proposed — pass IDs explicitly
    # so stale 'proposed'-status rows in the DB can't be picked instead.
    eval_result = await evaluator(
        engine,
        candidate_ids=proposed_ids,
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
    for status in ("escalated", "needs_work", "borderline", "killed", "proposed"):
        if status in by_status:
            parts.append(f"{status}={len(by_status[status])}")
    parts.append(f"mode=trend×{trend_calls}+single×{single_item_calls}")

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
