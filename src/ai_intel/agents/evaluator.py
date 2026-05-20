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
import os
import time
from datetime import datetime, timezone

from sqlmodel import Session, select

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.agents.saturator import _parse_llm_json
from ai_intel.db.models import IdeaCandidate
from ai_intel.personas import KNOWN_PERSONAS, load_persona

logger = logging.getLogger(__name__)

# Delay between sequential persona-critic calls (seconds). Default 5.0 is
# sized for Anthropic Tier-1 API account constraints; Max-plan OAuth users
# can safely drop this to 1.0 or 0.5 to cut cycle time ~5x. Override via
# the EVALUATOR_PERSONA_DELAY_SECONDS env var.
PERSONA_DELAY_SECONDS = float(os.getenv("EVALUATOR_PERSONA_DELAY_SECONDS", "5.0"))


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


def _aggregate(
    persona_critiques: dict[str, dict],
    *,
    veto_below: int = 55,
    borderline_above: int = 60,
    escalate_at: int = 75,
    needs_work_at: int = 40,
) -> tuple[int, str, int, str | None]:
    """Aggregate persona subscores.

    Returns (overall_score, verdict, min_subscore, vetoer_persona_id).

    Rules:
      1. If ANY persona subscore < ``veto_below``:
         a. mean ≥ ``borderline_above`` → verdict='borderline' (user-visible:
            critics couldn't all agree but the mean signals a real idea —
            usually a "good business that isn't venture-scale" pattern).
         b. otherwise → verdict='killed'.
      2. No veto: verdict by mean — ≥escalate_at → 'escalated',
         ≥needs_work_at → 'needs_work', else 'killed'.

    Borderline carves a strict subset out of the kill path; it does NOT
    weaken the veto semantics. The vetoer_persona_id is still set so the
    user sees who pushed back.
    """
    if not persona_critiques:
        return 0, "killed", 0, None

    items = [
        (pid, int(v.get("subscore", 0)))
        for pid, v in persona_critiques.items()
    ]
    subs = [s for _, s in items]
    min_pid, min_sub = min(items, key=lambda kv: kv[1])
    mean = sum(subs) / len(subs)
    score = int(round(mean))

    if min_sub < veto_below:
        if score >= borderline_above:
            return score, "borderline", min_sub, min_pid
        return score, "killed", min_sub, min_pid

    if score >= escalate_at:
        verdict = "escalated"
    elif score >= needs_work_at:
        verdict = "needs_work"
    else:
        verdict = "killed"
    return score, verdict, min_sub, None


def _load_candidate(engine, candidate_id: int) -> IdeaCandidate | None:
    with Session(engine) as s:
        return s.get(IdeaCandidate, candidate_id)


def _pending_candidate_ids(engine, limit: int) -> list[int]:
    """Return up to ``limit`` candidate ids with status='proposed', newest
    first. Newest-first matches the "evaluate what was just proposed"
    intent — otherwise stale stuck rows poison the queue."""
    with Session(engine) as s:
        rows = list(s.exec(
            select(IdeaCandidate.id)
            .where(IdeaCandidate.status == "proposed")
            .order_by(IdeaCandidate.proposed_at.desc())
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
    candidate_ids: list[int] | None = None,
    batch_limit: int = 5,
    model: str = "claude-haiku-4-5",
    escalate_threshold: int = 75,
    needs_work_threshold: int = 40,
):
    """Score one or many IdeaCandidate rows.

    Selection priority:
      1. ``candidate_id=X`` — evaluate exactly that one
      2. ``candidate_ids=[...]`` — evaluate exactly that list (used by the
         orchestrator so freshly-proposed rows can't be shadowed by stale
         pending rows lying around in the DB)
      3. Otherwise pull up to ``batch_limit`` newest pending rows

    Returns AgentResult dict — summary lists IDs evaluated + their verdicts.
    """
    if candidate_id is not None:
        ids = [candidate_id]
    elif candidate_ids:
        ids = list(candidate_ids)
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
                time.sleep(PERSONA_DELAY_SECONDS)
            first_call = False
            try:
                persona_text = load_persona(pid)
            except FileNotFoundError:
                # Persona file deleted/renamed — log loudly so the operator
                # notices, then skip. Silently degrading from 6 critics to 5
                # is the kind of bug that takes weeks to spot.
                logger.warning(
                    "evaluator: persona file for %r not found — skipping. "
                    "Expected src/ai_intel/personas/%s.md",
                    pid, pid,
                )
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

        score, verdict, min_sub, vetoer = _aggregate(
            persona_critiques,
            veto_below=55,
            escalate_at=escalate_threshold,
            needs_work_at=needs_work_threshold,
        )

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

        tag = f"#{cid}: mean={score}/100 min={min_sub}/100 → {verdict}"
        if vetoer:
            tag += f"  (vetoed by {vetoer})"
        summaries.append(tag)

    return {
        "summary": "; ".join(summaries),
        "prompt_tokens": total_pt,
        "completion_tokens": total_ct,
        "cost_usd": total_cost,
        "auth_mode": auth_mode_seen,
        "output_pointer": json.dumps({"evaluated_ids": ids}),
    }
