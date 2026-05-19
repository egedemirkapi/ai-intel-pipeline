"""Saturator agent — judges how crowded a tech/product space already is.

Given a topic string (e.g. "AI voice agents", "vector databases"), pulls
recent intel via semantic recall, asks an LLM to:
  1. Count and name direct competitors mentioned in the recent corpus
  2. Score saturation 0.0 (empty space) - 1.0 (totally crowded)
  3. Justify with concrete citations from the recall hits

Writes a SaturationAssessment row. The proposer agent reads these to
avoid pitching ideas in already-crowded spaces.

Caching: assessments older than 7 days are considered stale; the agent
will redo a topic if asked even if a non-stale row exists, but the
typical caller checks freshness first.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.db.models import SaturationAssessment
from ai_intel.memory.retrieve import recall

logger = logging.getLogger(__name__)


SATURATION_PROMPT = """You assess startup market saturation. Read the
RECENT NEWS ITEMS below and answer about the TOPIC.

TOPIC: {topic}

RECENT NEWS ITEMS (most recent first):
{hits_block}

Return ONLY a JSON object with these keys (no other text):
{{
  "score": <float between 0.0 and 1.0, where 0 = empty space, 1 = crowded>,
  "competitor_count": <integer — how many distinct funded/launched competitors you see>,
  "competitor_names": [<list of distinct company/product names mentioned>],
  "reasoning": "<2-3 sentences justifying the score>",
  "verdict": "<one of: empty, emerging, active, crowded, saturated>"
}}

Scoring rubric:
- 0.0-0.2 empty: no real competitors found
- 0.2-0.4 emerging: 1-3 small players, lots of greenfield
- 0.4-0.6 active: 5-10 players, well-funded leaders forming
- 0.6-0.8 crowded: 10+ players, clear category leader, hard to differentiate
- 0.8-1.0 saturated: dominant incumbent + many clones, terrible odds

Be honest. Don't inflate saturation; don't pretend a real category is empty."""


def _format_hits(hits) -> str:
    """Render recall hits as a numbered list the LLM can cite."""
    if not hits:
        return "(no recent items found)"
    lines = []
    for i, h in enumerate(hits, 1):
        when = h.published_at.strftime("%Y-%m-%d") if h.published_at else "—"
        snippet = (h.snippet or "").replace("\n", " ")[:200]
        lines.append(f"[{i}] {when}  {h.source}  {h.title}\n     {snippet}")
    return "\n".join(lines)


def _parse_llm_json(text: str) -> dict:
    """Extract the JSON object from LLM output, tolerant of trailing prose."""
    text = (text or "").strip()
    # If wrapped in ```json fences, strip them
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    # Find the first { and last } and take that slice
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in LLM output: {text[:200]!r}")
    return json.loads(text[start : end + 1])


@agent("saturator")
async def saturator(
    engine,
    *,
    topic: str,
    k: int = 12,
    cache_ttl_days: int = 7,
    use_cache: bool = True,
    model: str = "claude-haiku-4-5",
):
    """Assess saturation for ``topic``. Writes a SaturationAssessment row.

    Returns AgentResult dict.
    """
    topic = (topic or "").strip()
    if not topic:
        return {
            "summary": "empty topic — skipped",
            "auth_mode": None,
        }

    now = datetime.now(timezone.utc)

    if use_cache:
        with Session(engine) as s:
            existing = s.exec(
                select(SaturationAssessment)
                .where(SaturationAssessment.topic == topic)
                .where(SaturationAssessment.expires_at > now)
            ).first()
            if existing is not None:
                return {
                    "summary": (
                        f"cache hit: {topic!r} score={existing.score:.2f} "
                        f"({existing.competitor_count} competitors)"
                    ),
                    "auth_mode": None,
                    "output_pointer": json.dumps({"saturation_id": existing.id}),
                }

    # Pull recent intel that semantically matches the topic
    hits = recall(engine, topic, k=k, hit_types=("item",), log_query=False)
    hits_block = _format_hits(hits)

    messages = [
        {"role": "user", "content": SATURATION_PROMPT.format(
            topic=topic, hits_block=hits_block,
        )},
    ]

    resp = call_llm(
        messages,
        prefer="oauth",
        model=model,
        max_tokens=600,
        temperature=0.2,
    )

    try:
        parsed = _parse_llm_json(resp.text)
    except (ValueError, json.JSONDecodeError) as exc:
        logger.error("saturator LLM output unparseable for %r: %s", topic, exc)
        return {
            "summary": f"unparseable LLM output for {topic!r}: {exc}",
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "cost_usd": resp.cost_usd,
            "auth_mode": resp.auth_mode,
        }

    score = float(parsed.get("score", 0.0))
    score = max(0.0, min(1.0, score))
    competitor_count = int(parsed.get("competitor_count", 0))
    competitor_names = parsed.get("competitor_names", [])
    reasoning = str(parsed.get("reasoning", ""))[:1000]
    verdict = str(parsed.get("verdict", "unknown"))[:32]

    row = SaturationAssessment(
        topic=topic,
        score=score,
        competitor_count=competitor_count,
        sources_json=json.dumps({
            "competitor_names": competitor_names,
            "hit_item_ids": [h.id for h in hits if h.hit_type == "item"],
        }),
        assessed_at=now,
        expires_at=now + timedelta(days=cache_ttl_days),
        notes=f"verdict={verdict}; {reasoning}",
    )
    with Session(engine) as s:
        s.add(row)
        s.commit()
        s.refresh(row)
        sat_id = row.id

    return {
        "summary": (
            f"{topic!r} → score={score:.2f} verdict={verdict} "
            f"competitors={competitor_count}"
        ),
        "prompt_tokens": resp.prompt_tokens,
        "completion_tokens": resp.completion_tokens,
        "cost_usd": resp.cost_usd,
        "auth_mode": resp.auth_mode,
        "output_pointer": json.dumps({"saturation_id": sat_id}),
    }
