"""Proposer agent — generates startup-idea candidates.

Pipeline:
  1. Pick a *tech signal* (a recent novel item from the intel feed)
  2. Pick a *pain cluster* (a recent item from pain_sources)
  3. Recall the most-relevant founder essays for the pair
  4. Compose a prompt with both contexts + persona excerpts
  5. Ask LLM to draft a single concrete candidate idea

Writes one IdeaCandidate row per proposal with status="proposed".
Evaluator picks them up next.

The proposer DOESN'T self-judge — it just produces. Evaluator's job to
reject. This separation makes each agent simpler and more cacheable.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.agents.saturator import saturator as _saturator
from ai_intel.db.models import IdeaCandidate, Item, SaturationAssessment
from ai_intel.memory.retrieve import recall
from ai_intel.personas import load_persona
from sqlmodel import desc

logger = logging.getLogger(__name__)


PROPOSER_PROMPT = """You're brainstorming a single startup idea by combining
a NEW TECH SIGNAL with a REAL USER PAIN, grounded in founder wisdom.

NEW TECH SIGNAL (recent in the AI/tech world):
{tech_block}

USER PAIN (from an "Ask HN" style thread):
{pain_block}

FOUNDER WISDOM (relevant excerpts from {persona_name}):
{persona_block}

RELATED PAUL GRAHAM ESSAYS (titles you can think about):
{essays_block}

Propose ONE concrete candidate idea that:
- uses the new tech to address the pain
- is something the founder could actually build (no "AI-for-everything")
- avoids saturated patterns (if the tech signal already implies many competitors, pivot to a specific underserved wedge)

Return ONLY a JSON object (no other text):
{{
  "idea": "<one-sentence pitch in the form: 'X for Y who Z'>",
  "tech_basis": "<the new tech this leverages>",
  "pain_basis": "<the specific pain it solves>",
  "wedge": "<the narrow first-customer profile you'd target>",
  "key_assumption": "<the riskiest belief that must be true>",
  "validation_step": "<one cheap experiment to test that assumption in 7 days>"
}}

Be specific. Avoid 'platform', 'ecosystem', 'comprehensive', 'leverage'.
A vague idea is worse than no idea."""


def _format_item_block(item: Item | None, label: str) -> str:
    if item is None:
        return f"(no {label} available)"
    body = (item.body or "")[:600]
    return f"{item.title}\n{body}\n[source: {item.source} · {item.url}]"


def _format_essays_titles(hits) -> str:
    if not hits:
        return "(none found)"
    return "\n".join(f"- {h.title}" for h in hits[:6])


def _persona_excerpt(persona_id: str) -> tuple[str, str]:
    """Return (display_name, full markdown text)."""
    try:
        text = load_persona(persona_id)
    except FileNotFoundError:
        return (persona_id, "(persona not found)")
    nice_name = persona_id.replace("_", " ").title()
    return nice_name, text


def _pick_tech_signal(engine, days_back: int = 7) -> Item | None:
    """Pick a recent, non-pain-source, ai-relevant intel item we haven't
    already proposed an idea for."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    with Session(engine) as s:
        # Get recent intel items, exclude pain_source / founder_brain
        q = (
            select(Item)
            .where(Item.collected_at >= cutoff)
            .where(Item.source != "pain_source")
            .where(Item.source != "founder_brain")
            .where(Item.classification.is_not(None))  # noqa: E711
            .order_by(desc(Item.ai_relevance), desc(Item.collected_at))
            .limit(50)
        )
        candidates = list(s.exec(q))
        if not candidates:
            return None

        # Skip items already proposed-against
        already_used_urls = set(s.exec(
            select(IdeaCandidate.tech_basis).where(
                IdeaCandidate.proposed_at >= cutoff
            )
        ).all())
        fresh = [c for c in candidates if c.url not in already_used_urls]
        return random.choice(fresh) if fresh else candidates[0]


def _pick_pain(engine, days_back: int = 14) -> Item | None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    with Session(engine) as s:
        q = (
            select(Item)
            .where(Item.source == "pain_source")
            .where(Item.collected_at >= cutoff)
            .order_by(desc(Item.collected_at))
            .limit(30)
        )
        pains = list(s.exec(q))
    return random.choice(pains) if pains else None


async def _saturation_score(engine, topic: str, *, model: str) -> float | None:
    """Run (or fetch cached) saturator for a topic. Returns the score 0-1
    or None if assessment couldn't be made.
    """
    await _saturator(engine, topic=topic, use_cache=True, model=model)
    with Session(engine) as s:
        row = s.exec(
            select(SaturationAssessment)
            .where(SaturationAssessment.topic == topic)
            .order_by(desc(SaturationAssessment.assessed_at))
            .limit(1)
        ).first()
    return row.score if row else None


@agent("proposer")
async def proposer(
    engine,
    *,
    persona_id: str = "paul_graham",
    tech_signal: Item | None = None,
    pain: Item | None = None,
    model: str = "claude-haiku-4-5",
    saturation_threshold: float = 0.6,
    max_tries: int = 4,
):
    """Draft one IdeaCandidate by combining a tech signal + a pain + a
    founder lens. Returns AgentResult dict.

    Before drafting, runs the saturator on the candidate tech topic. If
    saturation exceeds ``saturation_threshold`` (default 0.6 = crowded),
    picks a different signal — up to ``max_tries`` attempts. This is the
    "don't propose in saturated spaces" rule the original plan demanded.

    Pass ``tech_signal`` / ``pain`` directly if you want determinism;
    otherwise the agent picks fresh items.
    """
    # Resolve tech signal — with saturation gate
    if tech_signal is not None:
        tech = tech_signal
        # Still check saturation, but don't loop (user picked deliberately)
        sat = await _saturation_score(engine, tech.title, model=model)
        if sat is not None and sat > saturation_threshold:
            return {
                "summary": (
                    f"explicit tech_signal {tech.title!r} saturated "
                    f"({sat:.2f} > {saturation_threshold}) — refusing to propose"
                ),
            }
    else:
        tech = None
        last_sat: float | None = None
        for _attempt in range(max_tries):
            candidate = _pick_tech_signal(engine)
            if candidate is None:
                break
            sat = await _saturation_score(engine, candidate.title, model=model)
            if sat is None or sat <= saturation_threshold:
                tech = candidate
                last_sat = sat
                break
            last_sat = sat
        if tech is None:
            return {
                "summary": (
                    f"every tech signal sampled (n={max_tries}) was saturated "
                    f"(last score {last_sat}) — nothing to propose"
                ),
            }

    pain_item = pain if pain is not None else _pick_pain(engine)
    # Pain is OK to be None — proposer can still work, the persona supplies
    # the founder-judgment lens. We just substitute "(none)" in the prompt.

    persona_name, persona_text = _persona_excerpt(persona_id)

    # Pull related essays as titles (cheap, no body) for context
    seed_q = (tech.title or "") + " " + (pain_item.title if pain_item else "")
    essay_hits = recall(
        engine, seed_q, k=6,
        source="founder_brain",
        hit_types=("item",),
        log_query=False,
    )

    prompt = PROPOSER_PROMPT.format(
        tech_block=_format_item_block(tech, "tech signal"),
        pain_block=_format_item_block(pain_item, "pain"),
        persona_name=persona_name,
        persona_block=persona_text,
        essays_block=_format_essays_titles(essay_hits),
    )

    resp = call_llm(
        [{"role": "user", "content": prompt}],
        prefer="oauth",
        model=model,
        max_tokens=900,
        temperature=0.8,  # encourage exploration
    )

    # Parse — reuse the tolerant JSON parser
    from ai_intel.agents.saturator import _parse_llm_json
    try:
        parsed = _parse_llm_json(resp.text)
    except (ValueError, json.JSONDecodeError) as exc:
        return {
            "summary": f"proposer LLM output unparseable: {exc}",
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "cost_usd": resp.cost_usd,
            "auth_mode": resp.auth_mode,
        }

    idea_text = str(parsed.get("idea", "")).strip()[:500]
    if not idea_text:
        return {"summary": "LLM returned empty idea — skipping"}

    now = datetime.now(timezone.utc)
    cand = IdeaCandidate(
        proposed_at=now,
        idea_text=idea_text,
        tech_basis=str(parsed.get("tech_basis", tech.title))[:300],
        status="proposed",
        # We piggyback on persona_critiques_json to store proposer detail
        # since IdeaCandidate doesn't have dedicated fields for wedge etc.
        persona_critiques_json=json.dumps({
            "_proposer_detail": {
                "wedge": parsed.get("wedge", ""),
                "key_assumption": parsed.get("key_assumption", ""),
                "validation_step": parsed.get("validation_step", ""),
                "pain_basis": parsed.get("pain_basis", ""),
                "persona_used": persona_id,
                "tech_signal_url": tech.url,
                "pain_url": pain_item.url if pain_item else None,
            }
        }),
    )

    with Session(engine) as s:
        s.add(cand)
        s.commit()
        s.refresh(cand)
        cid = cand.id

    return {
        "summary": f"#{cid}: {idea_text[:140]}",
        "prompt_tokens": resp.prompt_tokens,
        "completion_tokens": resp.completion_tokens,
        "cost_usd": resp.cost_usd,
        "auth_mode": resp.auth_mode,
        "output_pointer": json.dumps({"idea_candidate_id": cid}),
    }
