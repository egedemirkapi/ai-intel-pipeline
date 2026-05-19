"""Evaluator agent — strict multi-persona critic over IdeaCandidate rows.

Note: this agent fires 6 sequential Sonnet calls per candidate. Anthropic
Tier 1 (new accounts) rate limits make this fragile; we throttle to one
call per ~5s and rely on the runtime's 429 retry layer for the rest.

For each candidate, runs each of the 6 founder personas (Paul Graham,
Sam Altman, Garry Tan, Alex Hormozi, a16z, YC Partner) as an
independent critic. Each persona produces:
  - subscore 0-100
  - one-paragraph critique
  - the single kill criterion if they'd kill it

The agent then aggregates into:
  - overall score = mean of subscores
  - verdict:  score >= 75      → escalated (shown to user)
              40 <= score < 75 → needs_work
              score < 40       → killed

Aggregates are written back to the IdeaCandidate row.

Cost note: this is the only Phase 8 agent that defaults to Sonnet
(quality matters at the kill gate). 6 personas × ~1.5k tokens each =
~9k tokens per candidate. At Sonnet pricing that's roughly $0.13 per
candidate evaluated.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from sqlmodel import Session, select

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.agents.saturator import _parse_llm_json
from ai_intel.db.models import IdeaCandidate
from ai_intel.personas import KNOWN_PERSONAS, load_persona

logger = logging.getLogger(__name__)


CRITIC_PROMPT = """You are evaluating a startup-idea candidate using the
lens of ONE specific advisor. Stay strictly in their voice; don't blend
with others. Read their persona below carefully.

═══════════════════════════════════════════════════════════════════
PERSONA: {persona_name}

{persona_text}
═══════════════════════════════════════════════════════════════════

CANDIDATE IDEA:
  {idea_text}

TECH BASIS:   {tech_basis}
PAIN BASIS:   {pain_basis}
WEDGE:        {wedge}
KEY ASSUMPTION (what must be true):  {key_assumption}
VALIDATION STEP:  {validation_step}

Apply this persona's quick test + top questions + red flags. Be strict —
this advisor has reputation at stake. They've seen 1000 ideas; pattern-
match against the worst-case outcomes.

Return ONLY a JSON object (no other text):
{{
  "subscore": <int 0-100 — how strong is this idea from THIS advisor's lens>,
  "critique": "<2-4 sentences in this advisor's voice. cite their heuristics.>",
  "kill_criterion": "<the ONE thing this advisor would kill it on, if anything; 'none' if they'd green-light>",
  "would_fund_or_advise": <true | false>
}}

Scoring rubric (calibrate against this advisor's *actual* track record):
- 90-100: would actively pursue / fund
- 75-89:  intriguing, worth a deeper look
- 60-74:  has merit but big gaps
- 40-59:  unlikely to work as stated
- 0-39:   would advise against / kill"""


def _aggregate(persona_critiques: dict[str, dict]) -> tuple[int, str]:
    """Mean of subscores → verdict label."""
    subs = [int(v.get("subscore", 0)) for v in persona_critiques.values()]
    if not subs:
        return 0, "killed"
    mean = sum(subs) / len(subs)
    score = int(round(mean))
    if score >= 75:
        verdict = "escalated"
    elif score >= 40:
        verdict = "needs_work"
    else:
        verdict = "killed"
    return score, verdict


def _load_candidate(engine, candidate_id: int) -> IdeaCandidate | None:
    with Session(engine) as s:
        return s.get(IdeaCandidate, candidate_id)


def _pending_candidate_ids(engine, limit: int) -> list[int]:
    with Session(engine) as s:
        rows = list(s.exec(
            select(IdeaCandidate.id)
            .where(IdeaCandidate.status == "proposed")
            .order_by(IdeaCandidate.proposed_at)
            .limit(limit)
        ))
    return list(rows)


def _proposer_detail(cand: IdeaCandidate) -> dict:
    """Parse the proposer's metadata blob we stashed in persona_critiques_json."""
    raw = cand.persona_critiques_json or "{}"
    try:
        return json.loads(raw).get("_proposer_detail", {})
    except json.JSONDecodeError:
        return {}


@agent("evaluator")
async def evaluator(
    engine,
    *,
    candidate_id: int | None = None,
    batch_limit: int = 5,
    model: str = "claude-sonnet-4-6",
    escalate_threshold: int = 75,
    needs_work_threshold: int = 40,
):
    """Score one or many IdeaCandidate rows.

    If candidate_id is given, evaluate just that one. Otherwise pull up
    to ``batch_limit`` candidates with status="proposed" and evaluate
    each.

    Returns AgentResult dict — summary lists IDs evaluated + their verdicts.
    """
    if candidate_id is not None:
        ids = [candidate_id]
    else:
        ids = _pending_candidate_ids(engine, batch_limit)

    if not ids:
        return {"summary": "no candidates with status=proposed — nothing to do"}

    total_pt = 0
    total_ct = 0
    total_cost = 0.0
    auth_mode_seen: str | None = None
    summaries: list[str] = []

    for cid in ids:
        cand = _load_candidate(engine, cid)
        if cand is None:
            summaries.append(f"#{cid}: missing")
            continue

        detail = _proposer_detail(cand)

        persona_critiques: dict[str, dict] = {}

        # Run each persona as an independent critic, spaced to be kind to
        # Anthropic Tier-1 rate limits (~12 RPM for Sonnet, very tight TPM).
        first_call = True
        for pid in KNOWN_PERSONAS:
            if not first_call:
                time.sleep(5.0)
            first_call = False
            try:
                persona_text = load_persona(pid)
            except FileNotFoundError:
                continue
            prompt = CRITIC_PROMPT.format(
                persona_name=pid.replace("_", " ").title(),
                persona_text=persona_text,
                idea_text=cand.idea_text,
                tech_basis=cand.tech_basis or "(unspecified)",
                pain_basis=detail.get("pain_basis", "(unspecified)"),
                wedge=detail.get("wedge", "(unspecified)"),
                key_assumption=detail.get("key_assumption", "(unspecified)"),
                validation_step=detail.get("validation_step", "(unspecified)"),
            )

            resp = call_llm(
                [{"role": "user", "content": prompt}],
                prefer="oauth",
                model=model,
                max_tokens=600,
                temperature=0.3,
            )
            total_pt += resp.prompt_tokens
            total_ct += resp.completion_tokens
            total_cost += resp.cost_usd
            auth_mode_seen = auth_mode_seen or resp.auth_mode

            try:
                parsed = _parse_llm_json(resp.text)
            except Exception as exc:
                logger.warning(
                    "evaluator: %s critique unparseable for #%d: %s",
                    pid, cid, exc,
                )
                continue

            persona_critiques[pid] = {
                "subscore": int(parsed.get("subscore", 0)),
                "critique": str(parsed.get("critique", ""))[:1500],
                "kill_criterion": str(parsed.get("kill_criterion", ""))[:300],
                "would_fund": bool(parsed.get("would_fund_or_advise", False)),
            }

        if not persona_critiques:
            summaries.append(f"#{cid}: no critiques parsed")
            continue

        score, verdict = _aggregate(persona_critiques)

        # Override thresholds if the caller customized
        if score >= escalate_threshold:
            verdict = "escalated"
        elif score >= needs_work_threshold:
            verdict = "needs_work"
        else:
            verdict = "killed"

        # Preserve the proposer detail blob alongside the new critiques
        merged_blob: dict = {}
        if cand.persona_critiques_json:
            try:
                merged_blob = json.loads(cand.persona_critiques_json)
            except json.JSONDecodeError:
                merged_blob = {}
        merged_blob.update(persona_critiques)

        with Session(engine) as s:
            row = s.get(IdeaCandidate, cid)
            if row is None:
                continue
            row.evaluator_score = score
            row.evaluator_verdict = verdict
            row.status = verdict  # status mirrors verdict for easy filtering
            row.persona_critiques_json = json.dumps(merged_blob)
            s.add(row)
            s.commit()

        summaries.append(f"#{cid}: {score}/100 → {verdict}")

    return {
        "summary": "; ".join(summaries),
        "prompt_tokens": total_pt,
        "completion_tokens": total_ct,
        "cost_usd": total_cost,
        "auth_mode": auth_mode_seen,
        "output_pointer": json.dumps({"evaluated_ids": ids}),
    }
