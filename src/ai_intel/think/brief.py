"""The Briefing engine — assembles "what should I care about right now".

``build_brief()`` pulls these strands and returns a structured brief plus
a short spoken summary (used by the dashboard card, the ``brief.get``
chat tool, the ``brief.compose`` workflow action, and proactive voice):

    fresh        how much the collector has pulled recently (proof of life)
    news         the freshest intel items — newest collected first
    calendar     upcoming Google Calendar events
    homework     Google Classroom coursework due soon
    suggestions  intel matched to the user's interests (or trends, by default)

It is side-effect free — safe to call repeatedly / on a schedule.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, desc, func, select

from ai_intel.db.models import Item, TrendSynthesis
from ai_intel.think.interests import list_interests

logger = logging.getLogger(__name__)

# Knowledge-corpus sources are not "news" — keep them out of the brief.
_CORPUS_SOURCES = ("founder_brain", "failure_corpus")


def _fresh_counts(engine) -> dict:
    """How much the collector has pulled recently. This is what makes the
    24/7 collector *visible* — the numbers move every cycle."""
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        last_hour = s.exec(
            select(func.count(Item.id))
            .where(Item.collected_at >= now - timedelta(hours=1))
        ).first()
        today = s.exec(
            select(func.count(Item.id))
            .where(Item.collected_at >= now - timedelta(hours=24))
        ).first()
    return {"last_hour": int(last_hour or 0), "today": int(today or 0)}


def _top_news(
    engine,
    *,
    hours: int,
    limit: int,
    min_ai_relevance: float = 0.0,
) -> list[dict]:
    """The freshest intel items collected in the last ``hours`` — newest
    first, so the brief visibly reflects what the collector just pulled.
    (Ranking by AI-relevance instead made the brief look frozen: the same
    important story stayed on top for days even as new news arrived.)

    ``min_ai_relevance`` (default 0.0 — no filter) lets callers like the
    routine's ``news.open`` step demand AI-sector items only. The
    enrichment pipeline writes ``Item.ai_relevance`` in [0, 1]; 0.6 is
    a sensible "definitely AI-sector" threshold.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with Session(engine) as s:
        rows = list(s.exec(
            select(Item)
            .where(Item.collected_at >= cutoff)
            .where(Item.source.not_in(_CORPUS_SOURCES))
            .where(Item.ai_relevance.is_not(None))  # noqa: E711
            .where(Item.ai_relevance >= min_ai_relevance)
            .order_by(desc(Item.collected_at), desc(Item.ai_relevance))
            .limit(limit)
        ))
    return [
        {
            "id": it.id,
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "ai_relevance": it.ai_relevance,
            "collected_at": it.collected_at.isoformat() if it.collected_at else None,
        }
        for it in rows
    ]


def _recent_relevant(engine, *, k: int) -> list[dict]:
    """The most AI-relevant intel from the last week — the no-setup
    fallback for the suggestion section when there is nothing to match
    against (no interests, no trends)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    with Session(engine) as s:
        rows = list(s.exec(
            select(Item)
            .where(Item.collected_at >= cutoff)
            .where(Item.source.not_in(_CORPUS_SOURCES))
            .where(Item.ai_relevance.is_not(None))  # noqa: E711
            .order_by(desc(Item.ai_relevance))
            .limit(k)
        ))
    return [
        {
            "id": it.id,
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "score": it.ai_relevance,
        }
        for it in rows
    ]


def _trend_query(engine) -> str:
    """The active synthesized trend clusters, joined into one query
    string — used as a stand-in interest seed when the user has set none."""
    with Session(engine) as s:
        trends = list(s.exec(
            select(TrendSynthesis)
            .where(TrendSynthesis.status == "active")
            .order_by(desc(TrendSynthesis.generated_at))
            .limit(6)
        ))
    return "; ".join(t.cluster_label for t in trends if t.cluster_label)


def _interest_suggestions(engine, *, embedder, k: int) -> list[dict]:
    """Intel items matched to what the user cares about.

    Uses the user's interest notes when they have set any. When they have
    not, it seeds from the synthesizer's active trend clusters, and as a
    last resort falls back to recent high-relevance intel — so the brief
    always has useful suggestions, with no manual setup required."""
    interests = list_interests(engine)
    if interests:
        query = "; ".join(i["text"] for i in interests)
    else:
        query = _trend_query(engine)

    if query:
        try:
            from ai_intel.memory.retrieve import recall

            hits = recall(
                engine, query, k=k * 3, hit_types=("item",),
                embedder=embedder, log_query=False,
            )
            out: list[dict] = []
            for h in hits:
                if h.source in _CORPUS_SOURCES:
                    continue
                out.append({
                    "id": h.id,
                    "title": h.title,
                    "url": h.url,
                    "source": h.source,
                    "score": round(h.score, 3),
                })
                if len(out) >= k:
                    break
            if out:
                return out
        except Exception as exc:
            logger.debug("suggestion recall failed, falling back: %s", exc)

    # No interests, no trends, or recall came back empty — surface the
    # most relevant recent intel so the section is never blank.
    return _recent_relevant(engine, k=k)


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _compose_spoken(
    news: list[dict], calendar: dict, homework: dict,
    suggestions: list[dict], fresh: dict,
) -> str:
    """A short, natural-language brief — template-assembled, no LLM cost."""
    parts = [f"{_greeting()}. Here is your briefing."]
    # Lead with the collector's activity — this changes every cycle, so
    # the user can hear that fresh tech news really is flowing in.
    today = (fresh or {}).get("today", 0)
    last_hour = (fresh or {}).get("last_hour", 0)
    if today:
        if last_hour:
            parts.append(
                f"The intel collector pulled {last_hour} new "
                f"{'item' if last_hour == 1 else 'items'} in the last hour, "
                f"{today} today."
            )
        else:
            parts.append(f"The intel collector has gathered {today} items today.")
    if news:
        parts.append(f"Freshest in: {news[0]['title']}.")
        if len(news) > 1:
            parts.append(f"There are {len(news)} recent stories worth a look.")
    if calendar.get("summary"):
        parts.append(calendar["summary"])
    if homework.get("summary"):
        parts.append(homework["summary"])
    if suggestions:
        parts.append(f"You might want to read: {suggestions[0]['title']}.")
    quiet = (
        not news and not suggestions
        and not calendar.get("events") and not homework.get("assignments")
    )
    if quiet:
        parts.append("Nothing urgent right now — a quiet one.")
    return " ".join(parts)


async def build_brief(
    engine,
    *,
    news_hours: int = 36,
    news_limit: int = 5,
    days_ahead: int = 7,
    suggestion_limit: int = 5,
    embedder=None,
) -> dict:
    """Assemble the briefing. Side-effect free.

    Returns a dict with ``fresh``, ``news``, ``calendar``, ``homework``,
    ``suggestions``, a ``spoken`` summary string, and ``generated_at``.
    """
    # Reuse the workflow actions — they wrap the Google collectors and
    # degrade gracefully ("not connected") when there's no OAuth token.
    from ai_intel.workflows.actions.calendar import action_calendar_check
    from ai_intel.workflows.actions.classroom import action_classroom_check

    fresh = _fresh_counts(engine)
    news = _top_news(engine, hours=news_hours, limit=news_limit)
    calendar = await action_calendar_check(engine, days_ahead=days_ahead)
    homework = await action_classroom_check(engine, days_ahead=days_ahead)
    suggestions = _interest_suggestions(engine, embedder=embedder, k=suggestion_limit)
    spoken = _compose_spoken(news, calendar, homework, suggestions, fresh)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fresh": fresh,
        "news": news,
        "calendar": {
            "summary": calendar.get("summary", ""),
            "events": calendar.get("events", []),
        },
        "homework": {
            "summary": homework.get("summary", ""),
            "assignments": homework.get("assignments", []),
        },
        "suggestions": suggestions,
        "spoken": spoken,
    }
