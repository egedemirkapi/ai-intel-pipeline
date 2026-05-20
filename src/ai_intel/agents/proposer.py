"""Proposer agent — generates startup-idea candidates.

Pipeline:
  1. Pick a *tech signal* (a recent novel item from the intel feed)
  2. Pick a *pain cluster* (a recent item from pain_sources)
  3. Pull a saturation snapshot + adjacent recent items in the same space
  4. Recall real founder-essay passages (not just titles)
  5. Pull prior killed-idea attempts with overlapping tech_basis
  6. Pull failure-corpus parallels if any are ingested
  7. Compose a prompt with all of the above + the founder-persona lens
  8. Ask LLM to draft a single concrete candidate idea

Writes one IdeaCandidate row per proposal with status="proposed".
Evaluator picks them up next.

The proposer DOESN'T self-judge — it just produces. Evaluator's job to
reject. This separation makes each agent simpler and more cacheable.
"""
from __future__ import annotations

import html
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from ai_intel.agents.decorator import agent
from ai_intel.agents.runtime import call_llm
from ai_intel.agents.saturator import saturator as _saturator
from ai_intel.db.models import (
    IdeaCandidate,
    Item,
    SaturationAssessment,
    TrendSynthesis,
)
from ai_intel.memory.retrieve import recall
from ai_intel.personas import load_persona
from sqlmodel import desc

logger = logging.getLogger(__name__)


PROPOSER_PROMPT = """You are a founder reading this morning's tech news.
You've watched dozens of startups die — you know the failure patterns by
heart. You've internalized {persona_name}'s mental models so deeply they
feel like your own intuitions. You don't brainstorm random ideas. You
hunt for the *specific gap* a shift in the ecosystem just opened.

You're going to be shown one new tech signal, the items adjacent to it,
the saturation of that space, a current user pain, deep founder essay
excerpts, prior attempts that have already been killed, and post-mortems
of failed startups in adjacent territory. Your job is NOT to combine
these into an idea — it is to:

  1. **Recognize the underlying shift**. Look at the tech signal +
     adjacent items together. What's actually changing? What capability
     is becoming possible *now* that wasn't 12-24 months ago?
  2. **Identify the gap**. Cross-reference saturation, killed attempts,
     and failure parallels. What's *underserved*? Who has a real pain
     RIGHT NOW that this new capability makes solvable for the first
     time, that nobody is correctly attacking yet?
  3. **Propose into the gap**. Only then write a single concrete idea
     that lives in that gap — narrow enough to ship in 8 weeks,
     specific enough that a real person would say "yes I'd pay for that"
     when shown a working prototype.

──────── NEW TECH SIGNAL ────────
{tech_block}

──────── ADJACENT TECH (other recent items in this space) ────────
{adjacent_block}

──────── SATURATION OF THIS SPACE ────────
{saturation_block}

──────── USER PAIN ────────
{pain_block}

──────── FOUNDER WISDOM ({persona_name}) ────────
{persona_block}

──────── RELEVANT FOUNDER ESSAYS (real excerpts, not just titles) ────────
{essays_block}

──────── PRIOR KILLED ATTEMPTS in this space — don't repeat ────────
{killed_block}

──────── FAILURE PARALLELS (post-mortems of similar attempts) ────────
{failure_block}

Return ONLY a JSON object (no other text). The first three fields force
you to *think* before proposing — fill them honestly, not as marketing
copy:

{{
  "pattern_recognized": "<2-3 sentences: what shift is actually happening across the tech signal + adjacent items? What's becoming possible NOW?>",
  "gap_identified": "<2-3 sentences: who is hurting right now in a way this new capability can address? Why is nobody correctly attacking it yet? Be specific about the underserved corner.>",
  "failure_pattern_avoided": "<1-2 sentences: cite a specific failed attempt from the parallels above by name, name the pattern that killed it, and state how your idea sidesteps that pattern.>",
  "idea": "<one-sentence pitch in the form: 'X for Y who Z'>",
  "tech_basis": "<the new tech this leverages>",
  "pain_basis": "<the specific pain it solves>",
  "wedge": "<the narrow first-customer profile you'd target>",
  "key_assumption": "<the riskiest belief that must be true>",
  "validation_step": "<one cheap experiment to test that assumption in 7 days>",
  "why_now": "<what changed in the last 12 months that makes this possible NOW (cite the tech signal or an adjacent item if you can)>",
  "differentiation": "<how this differs from the killed attempts and current saturation — be specific about which competitor's gap you're attacking>"
}}

Be specific. Avoid 'platform', 'ecosystem', 'comprehensive', 'leverage',
'AI-powered'. A vague idea is worse than no idea. If the input doesn't
actually contain a real gap, say so honestly in `gap_identified` — but
still propose your best attempt. The evaluator can judge the rest."""


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_body(text: str, *, limit: int) -> str:
    """Strip HTML tags + decode entities + collapse whitespace + truncate.

    Some collectors (Google News in particular) embed `<a href>` blocks
    with encoded URLs in the body. That noise eats context window
    without adding signal, so we strip it before showing to the LLM.
    """
    text = _HTML_TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def _format_item_block(item: Item | None, label: str) -> str:
    if item is None:
        return f"(no {label} available)"
    body = _clean_body(item.body or "", limit=600)
    return f"{item.title}\n{body}\n[source: {item.source} · {item.url}]"


def _persona_excerpt(persona_id: str) -> tuple[str, str]:
    """Return (display_name, full markdown text)."""
    try:
        text = load_persona(persona_id)
    except FileNotFoundError:
        return (persona_id, "(persona not found)")
    nice_name = persona_id.replace("_", " ").title()
    return nice_name, text


def _recall_founder_passages(
    engine,
    query: str,
    *,
    k: int = 4,
    body_chars: int = 700,
) -> list[tuple[str, str]]:
    """Pull real essay passages from the founder corpus.

    Returns ``(title, body_excerpt)`` tuples — body is the first
    ``body_chars`` of the Item.body, not just the 240-char snippet
    that ``RecallResult`` normally exposes. The full body is what
    gives the LLM actual founder reasoning to chew on.
    """
    hits = recall(
        engine, query, k=k,
        source="founder_brain",
        hit_types=("item",),
        log_query=False,
    )
    out: list[tuple[str, str]] = []
    with Session(engine) as s:
        for h in hits:
            item = s.get(Item, h.id)
            if item is None:
                continue
            body = _clean_body(item.body or "", limit=body_chars)
            if not body:
                continue
            out.append((item.title, body))
    return out


def _recall_adjacent_tech(
    engine,
    query: str,
    *,
    exclude_url: str | None,
    k: int = 3,
) -> list[Item]:
    """Find other non-founder, non-pain items semantically near `query`.

    Gives the LLM a wider lens — "here are 2-3 OTHER things happening
    in this same space" — so it doesn't reason from a single point.
    """
    hits = recall(
        engine, query, k=k + 4,
        hit_types=("item",),
        log_query=False,
    )
    out: list[Item] = []
    seen_urls: set[str] = set()
    if exclude_url:
        seen_urls.add(exclude_url)
    with Session(engine) as s:
        for h in hits:
            item = s.get(Item, h.id)
            if item is None or item.url in seen_urls:
                continue
            if item.source in ("founder_brain", "pain_source", "failure_corpus"):
                continue
            seen_urls.add(item.url)
            out.append(item)
            if len(out) >= k:
                break
    return out


def _recent_killed_ideas(
    engine,
    tech_basis: str,
    *,
    k: int = 3,
    days_back: int = 90,
) -> list[IdeaCandidate]:
    """Pull recent killed candidates whose tech_basis overlaps."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    with Session(engine) as s:
        rows = list(s.exec(
            select(IdeaCandidate)
            .where(IdeaCandidate.status == "killed")
            .where(IdeaCandidate.proposed_at >= cutoff)
            .order_by(desc(IdeaCandidate.proposed_at))
            .limit(50)
        ))
    if not rows:
        return []
    tech_words = {w.lower() for w in tech_basis.split() if len(w) > 4}
    if not tech_words:
        return rows[:k]
    scored: list[tuple[int, IdeaCandidate]] = []
    for r in rows:
        rwords = {w.lower() for w in (r.tech_basis or "").split() if len(w) > 4}
        scored.append((len(tech_words & rwords), r))
    scored.sort(key=lambda x: -x[0])
    return [r for ov, r in scored[:k] if ov > 0]


def _failure_parallels(
    engine,
    query: str,
    *,
    k: int = 2,
    body_chars: int = 400,
) -> list[tuple[str, str]]:
    """Pull post-mortem parallels from failure_corpus. Empty if not ingested."""
    hits = recall(
        engine, query, k=k,
        source="failure_corpus",
        hit_types=("item",),
        log_query=False,
    )
    out: list[tuple[str, str]] = []
    with Session(engine) as s:
        for h in hits:
            item = s.get(Item, h.id)
            if item is None:
                continue
            out.append((item.title, _clean_body(item.body or "", limit=body_chars)))
    return out


def _saturation_block_text(engine, topic: str) -> str:
    with Session(engine) as s:
        row = s.exec(
            select(SaturationAssessment)
            .where(SaturationAssessment.topic == topic)
            .order_by(desc(SaturationAssessment.assessed_at))
            .limit(1)
        ).first()
    if row is None:
        return "(no saturation assessment available)"
    parts = [
        f"score={row.score:.2f}  (0=empty, 1=saturated)",
        f"competitor_count={row.competitor_count}",
    ]
    if row.notes:
        parts.append(f"notes: {row.notes[:300]}")
    return "\n".join(parts)


def _format_essays_block(passages: list[tuple[str, str]]) -> str:
    if not passages:
        return "(no founder essays matched — corpus may be unindexed)"
    chunks = []
    for title, body in passages:
        chunks.append(f"▸ {title}\n{body}")
    return "\n\n".join(chunks)


def _format_adjacent_block(items: list[Item]) -> str:
    if not items:
        return "(no adjacent tech items found)"
    return "\n".join(
        f"- {it.title} [{it.source}] — {_clean_body(it.body or '', limit=180)}"
        for it in items
    )


def _format_killed_block(killed: list[IdeaCandidate]) -> str:
    if not killed:
        return "(no recent killed attempts with overlapping tech)"
    chunks = []
    for k in killed:
        # Surface evaluator's verdict reason if present
        verdict = k.evaluator_verdict or "killed"
        chunks.append(
            f"- [{verdict}, score={k.evaluator_score}] {k.idea_text[:200]}"
        )
    return "\n".join(chunks)


def _format_failure_block(parallels: list[tuple[str, str]]) -> str:
    if not parallels:
        return "(no failure-corpus parallels — corpus may not be ingested yet)"
    chunks = []
    for title, body in parallels:
        chunks.append(f"▸ {title}\n{body}")
    return "\n\n".join(chunks)


# ─── Synthesizer-trend wiring ───────────────────────────────────────────
#
# When a fresh TrendSynthesis row exists, the proposer reasons about a
# META-PATTERN (e.g. "Local LLM inference on consumer GPUs") instead of
# a single news headline. The trend carries underlying_shift + new
# capability + the cluster of items that support it. This pushes the
# proposer from "reactive" to "deliberate ecosystem reasoner."


# Higher momentum → more likely to be picked when sampling among active trends.
_MOMENTUM_WEIGHTS: dict[str, float] = {
    "rising_fast":   4.0,
    "steady_rising": 3.0,
    "stable":        2.0,
    "slowing":       1.0,
}


def _pick_trend(engine) -> TrendSynthesis | None:
    """Pick one active TrendSynthesis row, weighted by momentum.

    Returns None if no active trends exist (proposer falls back to
    single-item mode). Weighted sampling ensures rising_fast trends are
    preferred but stable / slowing trends still rotate in occasionally.
    """
    with Session(engine) as s:
        rows = list(s.exec(
            select(TrendSynthesis)
            .where(TrendSynthesis.status == "active")
            .order_by(desc(TrendSynthesis.generated_at))
        ))
    if not rows:
        return None
    weights = [_MOMENTUM_WEIGHTS.get((r.momentum or "stable").lower(), 2.0)
               for r in rows]
    return random.choices(rows, weights=weights, k=1)[0]


def _load_trend_member_items(engine, trend: TrendSynthesis) -> list[Item]:
    """Fetch the Items referenced in trend.member_item_ids_json."""
    try:
        ids = json.loads(trend.member_item_ids_json or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(ids, list) or not ids:
        return []
    with Session(engine) as s:
        return [it for it in (s.get(Item, i) for i in ids) if it is not None]


def _format_trend_block(trend: TrendSynthesis, members: list[Item]) -> str:
    """Render a TrendSynthesis as the NEW TECH SIGNAL section.

    The LLM sees a meta-pattern + a sample of supporting items, NOT a
    single news headline. This is the architectural difference between
    'reactive' and 'deliberate' proposer reasoning.
    """
    try:
        convergence = json.loads(trend.convergence_with_json or "[]")
    except (json.JSONDecodeError, TypeError):
        convergence = []
    lines = [
        f"TREND: {trend.cluster_label}",
        f"MOMENTUM: {trend.momentum or 'stable'}  (cluster of {len(members)} items)",
        f"UNDERLYING SHIFT: {trend.underlying_shift or '(unspecified)'}",
        f"NEW CAPABILITY UNLOCKED: {trend.new_capability or '(unspecified)'}",
    ]
    if convergence:
        lines.append("CONVERGES WITH: " + ", ".join(str(c) for c in convergence))
    if members:
        lines.append("")
        lines.append("SUPPORTING ITEMS (sample of evidence):")
        for it in members[:6]:
            title = (it.title or "").strip()[:140]
            lines.append(f"  - [{it.source}] {title}")
    return "\n".join(lines)


def _format_adjacent_block_for_trend(members: list[Item]) -> str:
    """In trend mode the cluster members ARE the adjacent context."""
    if not members:
        return "(see SUPPORTING ITEMS above — trend members carry the adjacency context)"
    extra = members[6:12]  # show the second batch (first 6 already shown above)
    if not extra:
        return "(all member items already shown in the trend block above)"
    return "\n".join(
        f"- {it.title} [{it.source}] — {_clean_body(it.body or '', limit=180)}"
        for it in extra
    )


def _extract_entities(item: Item) -> list[str]:
    """Return non-trivial company + technology entities from item.entities_json.

    Enrichment writes ``{"companies": [...], "people": [...], "technologies":
    [...]}``. We use companies + technologies as trajectory signals — people
    mentions are too volatile to use as proxies for "new tech in the wild."
    """
    if not item.entities_json:
        return []
    try:
        data = json.loads(item.entities_json)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    out: list[str] = []
    for key in ("companies", "technologies"):
        for e in data.get(key, []) or []:
            if not isinstance(e, str):
                continue
            e = e.strip()
            if len(e) < 3:
                continue
            out.append(e)
    seen: set[str] = set()
    dedup: list[str] = []
    for e in out:
        k = e.lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(e)
    return dedup


def _entity_count_map(
    engine,
    *,
    since: datetime | None = None,
    before: datetime | None = None,
) -> dict[str, int]:
    """Aggregate per-entity mention counts in a time window.

    Returns ``{entity_lowercase: count}``. Counting happens via the parsed
    ``entities_json`` rather than full-text — much cheaper, and avoids
    spurious substring matches (e.g. 'AI' inside 'AirBnB').
    """
    counts: dict[str, int] = {}
    with Session(engine) as s:
        q = select(Item.entities_json).where(Item.entities_json.is_not(None))
        if since is not None:
            q = q.where(Item.collected_at >= since)
        if before is not None:
            q = q.where(Item.collected_at < before)
        for ej in s.exec(q):
            if not ej:
                continue
            try:
                data = json.loads(ej)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, dict):
                continue
            for key in ("companies", "technologies"):
                for e in data.get(key, []) or []:
                    if not isinstance(e, str):
                        continue
                    e = e.strip()
                    if len(e) < 3:
                        continue
                    k = e.lower()
                    counts[k] = counts.get(k, 0) + 1
    return counts


def _pick_tech_signal(engine, days_back: int = 14) -> Item | None:
    """Trajectory-aware pick: prefer signals that are NOVEL and ACCELERATING.

    For each entity (company/technology) found in items, compute mention
    counts in three windows: recent (last 7d), baseline (7-60d ago),
    historical (>60d ago). Then::

        novelty   = 1 / (1 + historical / 10)
        momentum  = recent / (1 + baseline)
        rising    = novelty * momentum * recent

    Items inherit the *max* rising-score across their entities. Multiplying
    by ``recent`` damps n=1 noise (entities that flickered once aren't a
    trend). Among the top-5 rising items we sample with weights so we
    don't lock onto the single most-rising signal every week.

    **Cold-start fallback**: if the DB has no baseline/historical entity
    counts yet (collector ran less than ~60 days), the trajectory math
    has nothing to bite on — it'd just rank by popularity, which is the
    OPPOSITE of what we want. So we fall back to picking from the rising
    long tail: entities with 3-to-(top-15%) mentions in the last 7 days,
    excluding the dominant brands. This gives a noticeably better signal
    than recency-ranking even with a fresh DB.
    """
    now = datetime.now(timezone.utc)
    recent_start = now - timedelta(days=7)
    baseline_start = now - timedelta(days=60)

    recent_counts = _entity_count_map(engine, since=recent_start)
    if not recent_counts:
        return None
    baseline_counts = _entity_count_map(
        engine, since=baseline_start, before=recent_start,
    )
    historical_counts = _entity_count_map(engine, before=baseline_start)

    has_history = bool(baseline_counts) or bool(historical_counts)
    max_recent = max(recent_counts.values()) if recent_counts else 0
    # Long-tail upper cutoff: anything above the top 15% of mention volume
    # is mainstream chatter (OpenAI / Anthropic / Google class) — drop it.
    # `max(5, ...)` keeps the cutoff useful on tiny databases where 15% < 5.
    tail_upper = max(5, int(max_recent * 0.15))

    entity_scores: dict[str, float] = {}
    for e_key, recent in recent_counts.items():
        if has_history:
            baseline = baseline_counts.get(e_key, 0)
            historical = historical_counts.get(e_key, 0)
            novelty = 1.0 / (1.0 + historical / 10.0)
            momentum = recent / (1.0 + baseline)
            entity_scores[e_key] = novelty * momentum * recent
        else:
            # Cold start — keep only the rising long tail. Filters out
            # one-off mentions (noise) AND the dominant brands (boring).
            if recent < 3 or recent > tail_upper:
                continue
            entity_scores[e_key] = float(recent)

    cutoff = now - timedelta(days=days_back)
    with Session(engine) as s:
        candidates = list(s.exec(
            select(Item)
            .where(Item.collected_at >= cutoff)
            .where(Item.source != "pain_source")
            .where(Item.source != "founder_brain")
            .where(Item.source != "failure_corpus")
            .where(Item.classification.is_not(None))
            .where(Item.entities_json.is_not(None))
            .limit(300)
        ))
        recent_tech_basis = [
            tb for tb in s.exec(
                select(IdeaCandidate.tech_basis)
                .where(IdeaCandidate.proposed_at >= cutoff)
            ).all() if tb
        ]

    scored: list[tuple[float, Item]] = []
    for item in candidates:
        ents = _extract_entities(item)
        if not ents:
            continue
        item_score = max(
            (entity_scores.get(e.lower(), 0.0) for e in ents),
            default=0.0,
        )
        if item_score <= 0:
            continue
        # Skip items whose title is already echoed in a recent tech_basis —
        # rough substring dedupe so we don't propose around the same news twice.
        title_lc = (item.title or "").lower()[:40]
        if title_lc and any(title_lc in (tb or "").lower() for tb in recent_tech_basis):
            continue
        scored.append((item_score, item))

    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    top = scored[:5]
    weights = [s for s, _ in top]
    items_only = [it for _, it in top]
    return random.choices(items_only, weights=weights, k=1)[0]


def _pick_tech_signal_recency(engine, days_back: int = 7) -> Item | None:
    """Legacy picker — kept for fallback. Sort by ai_relevance + recency."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    with Session(engine) as s:
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
    trend: TrendSynthesis | None = None,
    pain: Item | None = None,
    model: str = "claude-haiku-4-5",
    saturation_threshold: float = 0.6,
    max_tries: int = 4,
):
    """Draft one IdeaCandidate. Returns AgentResult dict.

    Operates in one of two modes:

    **Trend mode** (preferred, when ``trend`` is provided): the proposer
    reasons about a META-PATTERN identified by the synthesizer — a
    cluster of items + its underlying shift + the new capability it
    unlocks. This is "deliberate ecosystem reasoning" — the proposer
    doesn't react to a single news headline.

    **Single-item mode** (fallback): the proposer picks one tech signal
    via the trajectory-aware picker, runs a saturation gate, then reasons
    about that single item. Used when no active TrendSynthesis rows
    exist (cold start) or when the orchestrator explicitly opts out.

    Pass ``tech_signal`` / ``trend`` / ``pain`` directly for determinism;
    otherwise the agent picks fresh inputs.
    """
    using_trend = trend is not None
    # Resolve the tech basis — either the trend or a single Item
    tech: Item | None = None
    trend_members: list[Item] = []

    if using_trend:
        trend_members = _load_trend_member_items(engine, trend)
        tech_signal_summary = trend.cluster_label
        # tech_signal_url for _proposer_detail traceability: use the
        # first member's URL if available so the user can click through.
        tech_signal_url: str | None = (
            trend_members[0].url if trend_members else None
        )
    elif tech_signal is not None:
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
        tech_signal_summary = tech.title
        tech_signal_url = tech.url
    else:
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
        tech_signal_summary = tech.title
        tech_signal_url = tech.url

    pain_item = pain if pain is not None else _pick_pain(engine)
    # Pain is OK to be None — proposer can still work, the persona supplies
    # the founder-judgment lens. We just substitute "(none)" in the prompt.

    persona_name, persona_text = _persona_excerpt(persona_id)

    # Seed query for retrieval: in trend mode we use the underlying-shift +
    # new-capability text so essay/failure recall hits semantically-deep
    # patterns rather than just topic keywords. In single-item mode we use
    # the item title + pain title as before.
    if using_trend:
        seed_q = " ".join(filter(None, [
            trend.cluster_label or "",
            trend.new_capability or "",
            trend.underlying_shift or "",
            pain_item.title if pain_item else "",
        ]))
    else:
        seed_q = (tech.title or "") + " " + (pain_item.title if pain_item else "")

    essay_passages = _recall_founder_passages(engine, seed_q, k=4)

    # Adjacent / killed / failure / saturation blocks differ slightly per mode
    if using_trend:
        adjacent_items = trend_members
        adjacent_block_text = _format_trend_block(trend, trend_members)
        secondary_adjacent_text = _format_adjacent_block_for_trend(trend_members)
        saturation_block_text = (
            f"(trend mode — synthesizer already filtered for emerging "
            f"clusters; this trend's momentum is '{trend.momentum or 'stable'}')"
        )
        killed = _recent_killed_ideas(engine, trend.cluster_label or "", k=3)
    else:
        adjacent_items = _recall_adjacent_tech(
            engine, tech.title or seed_q, exclude_url=tech.url, k=3,
        )
        adjacent_block_text = _format_item_block(tech, "tech signal")
        secondary_adjacent_text = _format_adjacent_block(adjacent_items)
        saturation_block_text = _saturation_block_text(engine, tech.title)
        killed = _recent_killed_ideas(engine, tech.title or "", k=3)

    failure_parallels = _failure_parallels(engine, seed_q, k=2)

    prompt = PROPOSER_PROMPT.format(
        tech_block=adjacent_block_text,
        adjacent_block=secondary_adjacent_text,
        saturation_block=saturation_block_text,
        pain_block=_format_item_block(pain_item, "pain"),
        persona_name=persona_name,
        persona_block=persona_text,
        essays_block=_format_essays_block(essay_passages),
        killed_block=_format_killed_block(killed),
        failure_block=_format_failure_block(failure_parallels),
    )

    resp = call_llm(
        [{"role": "user", "content": prompt}],
        prefer="oauth",
        model=model,
        max_tokens=1400,
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
    # tech_basis comes from the LLM's own labelling; fall back to the
    # trend/item we fed in so the IdeaCandidate row is never blank.
    default_tech_basis = trend.cluster_label if using_trend else tech_signal_summary
    cand = IdeaCandidate(
        proposed_at=now,
        idea_text=idea_text,
        tech_basis=str(parsed.get("tech_basis", default_tech_basis))[:300],
        trend_synthesis_id=(trend.id if using_trend else None),
        status="proposed",
        # We piggyback on persona_critiques_json to store proposer detail
        # since IdeaCandidate doesn't have dedicated fields for wedge etc.
        persona_critiques_json=json.dumps({
            "_proposer_detail": {
                # Entrepreneurial reasoning chain (new in Stage 3) — these
                # three fields capture the proposer's THOUGHT before its
                # proposal. Empty strings if the model skipped them.
                "pattern_recognized": parsed.get("pattern_recognized", ""),
                "gap_identified": parsed.get("gap_identified", ""),
                "failure_pattern_avoided": parsed.get("failure_pattern_avoided", ""),
                # Proposal artifacts
                "wedge": parsed.get("wedge", ""),
                "key_assumption": parsed.get("key_assumption", ""),
                "validation_step": parsed.get("validation_step", ""),
                "pain_basis": parsed.get("pain_basis", ""),
                "why_now": parsed.get("why_now", ""),
                "differentiation": parsed.get("differentiation", ""),
                "persona_used": persona_id,
                "tech_signal_url": tech_signal_url,
                "pain_url": pain_item.url if pain_item else None,
                # Trend-mode traceability — empty in single-item mode
                "trend_id": (trend.id if using_trend else None),
                "trend_label": (trend.cluster_label if using_trend else None),
                "trend_momentum": (trend.momentum if using_trend else None),
                "input_mode": "trend" if using_trend else "single_item",
                "context_depth": {
                    "essay_passages": len(essay_passages),
                    "adjacent_items": len(adjacent_items),
                    "killed_attempts": len(killed),
                    "failure_parallels": len(failure_parallels),
                },
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
