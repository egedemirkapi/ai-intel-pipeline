"""Refiner agent — iterate on an existing IdeaCandidate.

Given a candidate id + optional user guidance, the refiner:

  1. Loads the original idea + its proposer-detail reasoning chain +
     the evaluator's persona critiques.
  2. Identifies the WORST kill criterion (the vetoer's specific
     objection — the persona with the lowest subscore).
  3. Builds a refinement prompt that asks the LLM to ITERATE on the
     angle to address that critique while preserving founder-fit and
     the billion-dollar-market thesis.
  4. Writes a NEW IdeaCandidate row (status="proposed") linked back
     to the parent via ``_proposer_detail.refined_from_id``.
  5. The caller (typically the ``ideas.refine`` chat tool) runs the
     evaluator on the new candidate so the score change is visible
     immediately.

This is what turns the system from a one-shot generator into a
conversation: the user says *"refine #63 with stronger behavior-change
framing"* and the system iterates on that specific axis without
re-running the whole orchestrator.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlmodel import Session

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.agents.saturator import _parse_llm_json
from ai_intel.db.models import IdeaCandidate

logger = logging.getLogger(__name__)


REFINER_PROMPT = """You are refining an existing startup idea. The evaluator
already scored it and gave specific critiques. Your job is to ITERATE on
the angle to address the WORST critique while preserving the parts that
worked — founder-fit, the billion-dollar-market thesis, and any
defensible moat structure that survives the critique.

──────── ORIGINAL IDEA ────────
{original_idea}

──────── ORIGINAL REASONING CHAIN ────────
Pattern recognized: {pattern_recognized}
Gap identified: {gap_identified}
Founder fit: {founder_fit}
TAM signal: {tam_signal}
Behavior change unlock: {behavior_change_unlock}
Moat design: {moat_design}  (score: {moat_score})
Distribution path: {distribution_path}
Success pattern echoed: {success_pattern_echoed}
Wedge: {wedge}

──────── EVALUATOR'S WORST CRITIQUE ────────
From {worst_persona} (subscore: {worst_score}/100):
{worst_critique}

Kill criterion: {worst_kill}

──────── USER GUIDANCE (if any) ────────
{guidance}

──────── YOUR JOB ────────

Iterate the idea to address the worst critique. The goal is NOT to
preserve the original idea verbatim — it's to find the angle that
SURVIVES this specific critique while staying in the same founder-fit
domain and (ideally) the same trend.

Concretely:
  1. Read the critique carefully. What is the STRUCTURAL objection?
     ("TAM ceiling" / "no behavior change" / "no offer shape" / etc.)
  2. Identify which part of the original chain is causing the kill.
  3. PIVOT that part — change the wedge / change the moat shape /
     change the behavior-change framing / change the distribution path
     — as needed to address the objection.
  4. Re-design ALL the JSON fields, not just the changed one. (If you
     pivot the wedge, the moat probably changes too. Don't restate
     verbatim — iterate.)

Return ONLY a JSON object with the same structure as the proposer
output. Fill ALL fields — iterating means rewriting the whole chain
with the refined angle.

{{
  "pattern_recognized": "<2-3 sentences>",
  "gap_identified": "<2-3 sentences>",
  "founder_fit": "<2 sentences>",
  "tam_signal": "<$10M | $100M | $1B | $10B | $100B+ — with one sentence of reasoning>",
  "behavior_change_unlock": "<1-2 sentences — what NEW behavior does this enable?>",
  "moat_design": "<3-4 sentences — name the specific lock-in>",
  "moat_score": <integer 1-10, must be ≥6 — if you can't get to 6, the angle still needs more pivoting>,
  "distribution_path": "<2-3 sentences — how do the first 10K users arrive?>",
  "success_pattern_echoed": "<one company by name + which playbook element>",
  "failure_pattern_avoided": "<1-2 sentences>",
  "idea": "<one-sentence pitch in form 'X for Y who Z'>",
  "tech_basis": "<the new tech leveraged>",
  "pain_basis": "<the specific pain>",
  "wedge": "<first-100-users profile — wedge ≠ niche>",
  "key_assumption": "<the riskiest belief that must be true>",
  "validation_step": "<one cheap experiment in 7 days>",
  "why_now": "<what changed in the last 12 months>",
  "differentiation": "<the 10× dimension>"
}}

ITERATE — don't restate. If the original moat was 'integration depth'
and the critique was 'thin moat, hyperscaler clones it,' the refined
moat must be substantively DIFFERENT — a data network effect, a
regulatory trust requirement, a distribution lock — not a rephrasing.
"""


def _extract_worst_critique(blob: dict) -> tuple[str, int | None, str, str]:
    """Find the persona with the lowest subscore — that's the vetoer.

    Returns (persona_id, subscore, critique_text, kill_criterion_text).
    Returns sensible empty defaults if no critiques exist (e.g. the
    parent candidate was never evaluated — refining without a critique
    is less useful but still allowed via the `guidance` field).
    """
    critiques = {
        k: v for k, v in blob.items()
        if k != "_proposer_detail" and isinstance(v, dict)
    }
    if not critiques:
        return (
            "no_critique",
            None,
            "(no evaluator critique available — refining on guidance alone)",
            "",
        )
    worst_id, worst_blob = min(
        critiques.items(),
        key=lambda kv: kv[1].get("subscore", 100),
    )
    return (
        worst_id,
        worst_blob.get("subscore"),
        (worst_blob.get("critique") or "")[:700],
        (worst_blob.get("kill_criterion") or "")[:400],
    )


@agent("refiner")
async def refiner(
    engine,
    *,
    candidate_id: int,
    guidance: str = "",
    model: str = "claude-haiku-4-5",
):
    """Refine an existing IdeaCandidate by iterating on its weakest axis.

    Args:
        candidate_id: the IdeaCandidate id to refine.
        guidance:     optional user-supplied direction
                      (e.g. "stronger behavior-change framing",
                      "address the moat critique with a data network effect").
        model:        LLM to use (defaults to Haiku 4.5 for cost/throughput).

    Returns an AgentResult dict. The new candidate's id is in the
    ``output_pointer`` JSON as ``new_idea_candidate_id`` so the caller
    (typically the chat tool) can run the evaluator on it.
    """
    with Session(engine) as s:
        parent = s.get(IdeaCandidate, candidate_id)
    if parent is None:
        return {"summary": f"no IdeaCandidate with id={candidate_id}"}

    try:
        blob = json.loads(parent.persona_critiques_json or "{}")
    except (json.JSONDecodeError, TypeError):
        blob = {}
    pd = blob.get("_proposer_detail") or {}

    worst_persona, worst_score, worst_critique, worst_kill = (
        _extract_worst_critique(blob)
    )

    prompt = REFINER_PROMPT.format(
        original_idea=(parent.idea_text or "(no idea text)")[:600],
        pattern_recognized=(pd.get("pattern_recognized") or "")[:300],
        gap_identified=(pd.get("gap_identified") or "")[:300],
        founder_fit=(pd.get("founder_fit") or "")[:300],
        tam_signal=pd.get("tam_signal") or "(missing)",
        behavior_change_unlock=(pd.get("behavior_change_unlock") or "")[:300],
        moat_design=(pd.get("moat_design") or "")[:400],
        moat_score=pd.get("moat_score") if pd.get("moat_score") is not None else "?",
        distribution_path=(pd.get("distribution_path") or "")[:300],
        success_pattern_echoed=(pd.get("success_pattern_echoed") or "")[:200],
        wedge=(pd.get("wedge") or "")[:300],
        worst_persona=worst_persona,
        worst_score=worst_score if worst_score is not None else "?",
        worst_critique=worst_critique,
        worst_kill=worst_kill,
        guidance=(
            guidance.strip()
            or "(none — focus on addressing the evaluator's worst critique)"
        ),
    )

    resp = call_llm(
        [{"role": "user", "content": prompt}],
        prefer="oauth",
        model=model,
        max_tokens=3000,
        temperature=0.7,  # some exploration but tighter than fresh ideation
    )

    try:
        parsed = _parse_llm_json(resp.text)
    except (ValueError, json.JSONDecodeError) as exc:
        return {
            "summary": f"refiner LLM output unparseable: {exc}",
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "cost_usd": resp.cost_usd,
            "auth_mode": resp.auth_mode,
        }

    idea_text = str(parsed.get("idea", "")).strip()[:500]
    if not idea_text:
        return {"summary": "refiner returned empty idea — skipping"}

    now = datetime.now(timezone.utc)
    new_cand = IdeaCandidate(
        proposed_at=now,
        idea_text=idea_text,
        tech_basis=str(parsed.get("tech_basis", parent.tech_basis or ""))[:300],
        trend_synthesis_id=parent.trend_synthesis_id,
        status="proposed",
        persona_critiques_json=json.dumps({
            "_proposer_detail": {
                "pattern_recognized": parsed.get("pattern_recognized", ""),
                "gap_identified": parsed.get("gap_identified", ""),
                "founder_fit": parsed.get("founder_fit", ""),
                "tam_signal": parsed.get("tam_signal", ""),
                "behavior_change_unlock": parsed.get("behavior_change_unlock", ""),
                "moat_design": parsed.get("moat_design", ""),
                "moat_score": parsed.get("moat_score"),
                "distribution_path": parsed.get("distribution_path", ""),
                "success_pattern_echoed": parsed.get("success_pattern_echoed", ""),
                "failure_pattern_avoided": parsed.get("failure_pattern_avoided", ""),
                "wedge": parsed.get("wedge", ""),
                "key_assumption": parsed.get("key_assumption", ""),
                "validation_step": parsed.get("validation_step", ""),
                "pain_basis": parsed.get("pain_basis", ""),
                "why_now": parsed.get("why_now", ""),
                "differentiation": parsed.get("differentiation", ""),
                # Refinement-specific provenance
                "persona_used": "refiner",
                "input_mode": "refinement",
                "refined_from_id": parent.id,
                "refinement_guidance": (
                    guidance.strip()[:400] if guidance.strip() else None
                ),
                "addressed_critique_from": worst_persona,
                "addressed_kill_criterion": worst_kill[:300] if worst_kill else None,
                # Carry trend linkage from parent for evaluator context
                "trend_id": parent.trend_synthesis_id,
                "trend_label": pd.get("trend_label"),
                "trend_momentum": pd.get("trend_momentum"),
                "context_depth": {"refined_from": parent.id},
            },
        }),
    )

    with Session(engine) as s:
        s.add(new_cand)
        s.commit()
        s.refresh(new_cand)
        new_id = new_cand.id

    return {
        "summary": f"refined #{candidate_id} → #{new_id}: {idea_text[:120]}",
        "prompt_tokens": resp.prompt_tokens,
        "completion_tokens": resp.completion_tokens,
        "cost_usd": resp.cost_usd,
        "auth_mode": resp.auth_mode,
        "output_pointer": json.dumps({
            "new_idea_candidate_id": new_id,
            "refined_from_id": candidate_id,
            "addressed_critique_from": worst_persona,
        }),
    }
