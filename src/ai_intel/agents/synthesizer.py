"""Synthesizer agent — ecosystem-level trend recognition.

This is the deep-reasoning piece that turns the proposer from "reactive
synthesizer" (one news item → one idea) into "deliberate founder doing
pattern recognition" (whole ecosystem → convergent trends → ideas
proposed against those trends).

Pipeline:
  1. Pull all intel items collected in the last N days (default 14)
  2. Feed their titles + short summaries to one LLM call
  3. Ask the LLM to identify 5-8 CONVERGENT TRENDS — clusters of news
     that point at the same underlying shift in the ecosystem
  4. For each trend, capture:
     - cluster_label   — short tag for the trend
     - underlying_shift — what's actually changing
     - new_capability  — what becomes possible NOW
     - momentum        — rising_fast | steady_rising | stable | slowing
     - convergence_with — other clusters this one combines with
     - member item ids — which intel items belong to this cluster
  5. Write each as a TrendSynthesis row

The proposer can then read recent TrendSynthesis rows and reason
against META-PATTERNS instead of individual news items. That's the
"don't react to every update; reason deeply across the ecosystem"
intent.

Cost (Haiku, ~180 items): ~10-15k prompt tokens, ~3k completion =
about $0.05 per synthesis run. Designed to run daily or weekly.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, desc, select

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.agents.saturator import _parse_llm_json
from ai_intel.db.models import Item, TrendSynthesis

logger = logging.getLogger(__name__)


SYNTHESIZER_PROMPT = """You are a tech analyst with deep founder intuition.
Below are {n_items} recent intel items from the AI / tech ecosystem,
collected over the last {days} days. They include news headlines, HN /
Reddit posts, RSS articles, and Product Hunt launches.

Your job is NOT to summarize each one. Your job is to find the
**convergent trends** — clusters of items that point at the same
underlying shift in the ecosystem. Like a founder reading the morning
news, you're looking for the 5-8 things that, taken together, tell you
where the world is moving and what's becoming possible NOW that wasn't
possible 12-24 months ago.

For each trend you identify:
  - Give it a SHORT label (3-6 words, no fluff: "Local LLM inference
    on consumer GPUs", "Open-source coding agents", "Verticalized AI
    voice agents")
  - List the indices of the items you grouped into it (e.g. [3, 17, 42])
  - Articulate the UNDERLYING SHIFT in 1-2 sentences (what's actually
    changing — not the headline, the deeper movement)
  - Name the NEW CAPABILITY becoming possible (1 sentence — what can
    a founder do NOW that they couldn't 12 months ago?)
  - Rate the MOMENTUM: "rising_fast" | "steady_rising" | "stable" | "slowing"
  - Name 0-2 other cluster labels (from your own list) this one
    converges with — where DOES this combine with another shift to
    open a different kind of gap?
  - Estimate the MARKET SIGNAL — three fields, honest order-of-magnitude:
    * tam_billions_estimate: a float — your best guess at the TAM in $B
      if a winner emerges. A narrow niche is 0.5; a smartphone-scale
      shift is 300+; AI dev-tools is ~30; cloud infra is ~500.
    * addressable_users_profile: one sentence — who's the buyer/user
      ("AI infrastructure teams at mid-to-large companies", "every
      consumer with a smartphone", "PhD students at R1 universities").
    * natural_distribution: one sentence — how this would naturally
      reach scale ("Developer WOM + freemium tier", "Enterprise sales
      via cloud-provider partnerships", "Viral via shareable artifacts").

INTEL ITEMS:
{items_block}

Return ONLY a JSON object with this exact shape (no other text):
{{
  "trends": [
    {{
      "cluster_label": "<short tag>",
      "member_indices": [<int>, <int>, ...],
      "underlying_shift": "<1-2 sentences>",
      "new_capability": "<1 sentence>",
      "momentum": "rising_fast|steady_rising|stable|slowing",
      "convergence_with": ["<other cluster_label>", ...],
      "market_signal": {{
        "tam_billions_estimate": <float>,
        "addressable_users_profile": "<1 sentence>",
        "natural_distribution": "<1 sentence>"
      }}
    }},
    ...
  ]
}}

Rules:
- 5-8 trends total. Not 2, not 15.
- A trend must have ≥3 member items. Otherwise it's noise, drop it.
- Be SPECIFIC. "AI" is not a trend. "Open-source MoE inference on
  consumer GPUs becomes viable" IS a trend.
- The convergence_with field can be empty [] if a trend stands alone.
  But many real trends combine — name the combinations honestly.
"""


def _gather_items(engine, *, days: int, max_items: int) -> list[Item]:
    """Pull recent intel items, excluding the founder + failure corpora.

    Sorted by ai_relevance descending so the most-AI-relevant items come
    first, then capped at max_items. The cap keeps the prompt bounded.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with Session(engine) as s:
        rows = list(s.exec(
            select(Item)
            .where(Item.collected_at >= cutoff)
            .where(Item.source != "founder_brain")
            .where(Item.source != "failure_corpus")
            .where(Item.source != "pain_source")
            .where(Item.classification.is_not(None))
            .order_by(desc(Item.ai_relevance), desc(Item.collected_at))
            .limit(max_items)
        ))
    return rows


def _format_items_block(items: list[Item], *, summary_chars: int = 140) -> str:
    """Title + short body summary, one per line, indexed from 1.

    Total budget per item ~200 chars; 180 items × 200 = ~36KB which
    Haiku handles comfortably.
    """
    lines: list[str] = []
    for i, it in enumerate(items, 1):
        title = (it.title or "").strip().replace("\n", " ")[:160]
        body = (it.body or "").strip().replace("\n", " ")[:summary_chars]
        if body:
            lines.append(f"{i}. [{it.source}] {title} — {body}")
        else:
            lines.append(f"{i}. [{it.source}] {title}")
    return "\n".join(lines)


def _coerce_trend(raw: dict[str, Any], items: list[Item]) -> dict[str, Any] | None:
    """Validate + materialize one trend dict from the LLM.

    Maps LLM-returned 1-based ``member_indices`` to actual Item ids,
    silently drops out-of-range indices. Returns None if the trend
    doesn't meet the >=3-members rule.
    """
    label = (raw.get("cluster_label") or "").strip()
    if not label:
        return None
    indices = raw.get("member_indices") or []
    if not isinstance(indices, list):
        return None
    item_ids: list[int] = []
    for idx in indices:
        try:
            i = int(idx)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(items) and items[i - 1].id is not None:
            item_ids.append(items[i - 1].id)  # type: ignore[arg-type]
    if len(item_ids) < 3:
        return None
    convergence = raw.get("convergence_with") or []
    if not isinstance(convergence, list):
        convergence = []

    # Market-signal estimate (idea-finder v2). Honest order-of-magnitude
    # TAM + who-the-user-is + how-it-distributes. Drops cleanly to None
    # if the LLM omitted it (older synthesis rows pre-v2).
    market_signal: dict[str, Any] | None = None
    raw_ms = raw.get("market_signal")
    if isinstance(raw_ms, dict):
        tam_val = raw_ms.get("tam_billions_estimate")
        try:
            tam_float = float(tam_val) if tam_val is not None else None
        except (TypeError, ValueError):
            tam_float = None
        market_signal = {
            "tam_billions_estimate": tam_float,
            "addressable_users_profile": str(
                raw_ms.get("addressable_users_profile") or ""
            ).strip()[:400],
            "natural_distribution": str(
                raw_ms.get("natural_distribution") or ""
            ).strip()[:400],
        }

    return {
        "cluster_label": label[:120],
        "member_item_ids": item_ids,
        "underlying_shift": (raw.get("underlying_shift") or "").strip()[:1000],
        "new_capability": (raw.get("new_capability") or "").strip()[:600],
        "momentum": (raw.get("momentum") or "stable").strip()[:32],
        "convergence_with": [str(c).strip()[:120] for c in convergence if c],
        "market_signal": market_signal,
    }


def _mark_prior_stale(session: Session, before: datetime) -> int:
    """Mark any active TrendSynthesis row whose generated_at is older
    than this run's generated_at as 'stale'. Keeps history queryable
    but ensures the proposer reads only the freshest set."""
    stale = list(session.exec(
        select(TrendSynthesis)
        .where(TrendSynthesis.status == "active")
        .where(TrendSynthesis.generated_at < before)
    ))
    for row in stale:
        row.status = "stale"
        session.add(row)
    return len(stale)


@agent("synthesizer")
async def synthesizer(
    engine,
    *,
    days: int = 14,
    max_items: int = 180,
    model: str = "claude-haiku-4-5",
):
    """Run one synthesis pass over the recent intel ecosystem.

    Writes 5-8 TrendSynthesis rows. Prior active rows are demoted to
    'stale' so downstream consumers (the proposer) only see the newest
    snapshot when querying ``status='active'``.

    Args:
        days: how far back to look for intel items (default 14)
        max_items: cap on items shipped to the LLM (default 180 = ~36KB
            prompt at 200 chars/item, fits comfortably in Haiku context)
        model: LLM to use for the synthesis call

    Returns AgentResult dict — summary lists the trends produced.
    """
    now = datetime.now(timezone.utc)
    items = _gather_items(engine, days=days, max_items=max_items)
    if len(items) < 20:
        return {
            "summary": (
                f"only {len(items)} intel items in last {days}d — "
                f"too thin to synthesize trends"
            ),
        }

    prompt = SYNTHESIZER_PROMPT.format(
        n_items=len(items),
        days=days,
        items_block=_format_items_block(items),
    )

    resp = call_llm(
        [{"role": "user", "content": prompt}],
        prefer="oauth",
        model=model,
        max_tokens=3000,
        temperature=0.4,  # we want consistent reasoning, not exploration
    )

    try:
        parsed = _parse_llm_json(resp.text)
    except (ValueError, json.JSONDecodeError) as exc:
        return {
            "summary": f"synthesizer LLM output unparseable: {exc}",
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "cost_usd": resp.cost_usd,
            "auth_mode": resp.auth_mode,
        }

    raw_trends = parsed.get("trends") or []
    if not isinstance(raw_trends, list) or not raw_trends:
        return {
            "summary": "synthesizer returned no trends",
            "prompt_tokens": resp.prompt_tokens,
            "completion_tokens": resp.completion_tokens,
            "cost_usd": resp.cost_usd,
            "auth_mode": resp.auth_mode,
        }

    written = 0
    written_labels: list[str] = []
    window_start = now - timedelta(days=days)

    with Session(engine) as s:
        _mark_prior_stale(s, before=now)
        for raw_trend in raw_trends:
            coerced = _coerce_trend(raw_trend, items)
            if coerced is None:
                continue
            row = TrendSynthesis(
                generated_at=now,
                window_start=window_start,
                window_end=now,
                cluster_label=coerced["cluster_label"],
                member_item_ids_json=json.dumps(coerced["member_item_ids"]),
                underlying_shift=coerced["underlying_shift"],
                new_capability=coerced["new_capability"],
                momentum=coerced["momentum"],
                convergence_with_json=json.dumps(coerced["convergence_with"]),
                market_signal_json=(
                    json.dumps(coerced["market_signal"])
                    if coerced.get("market_signal") else None
                ),
                raw_llm_json=json.dumps(raw_trend),
                status="active",
            )
            s.add(row)
            written_labels.append(coerced["cluster_label"])
            written += 1
        s.commit()

    summary = f"synthesized {written} trends from {len(items)} items: " + " · ".join(
        f"'{lbl}'" for lbl in written_labels
    )
    return {
        "summary": summary,
        "prompt_tokens": resp.prompt_tokens,
        "completion_tokens": resp.completion_tokens,
        "cost_usd": resp.cost_usd,
        "auth_mode": resp.auth_mode,
        "output_pointer": json.dumps({"trend_count": written}),
    }
