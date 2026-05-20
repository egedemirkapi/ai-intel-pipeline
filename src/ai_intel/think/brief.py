"""The Briefing engine — assembles "what should I care about right now".

``build_brief()`` pulls four strands and returns a structured brief plus
a short spoken summary (used by the dashboard card, the ``brief.get``
chat tool, the ``brief.compose`` workflow action, and — in Sprint 3 —
proactive voice):

    news         top recent intel items, ranked by AI-relevance
    calendar     upcoming Google Calendar events
    homework     Google Classroom coursework due soon
    suggestions  intel items semantically matched to the user's interests

It is side-effect free — safe to call repeatedly / on a schedule.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, desc, select

from ai_intel.db.models import Item
from ai_intel.think.interests import list_interests

logger = logging.getLogger(__name__)

# Knowledge-corpus sources are not "news" — keep them out of the brief.
_CORPUS_SOURCES = ("founder_brain", "failure_corpus")


def _top_news(engine, *, hours: int, limit: int) -> list[dict]:
    """Most AI-relevant intel items collected in the last ``hours``."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with Session(engine) as s:
        rows = list(s.exec(
            select(Item)
            .where(Item.collected_at >= cutoff)
            .where(Item.source.not_in(_CORPUS_SOURCES))
            .where(Item.ai_relevance.is_not(None))  # noqa: E711
            .order_by(desc(Item.ai_relevance))
            .limit(limit)
        ))
    return [
        {
            "id": it.id,
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "ai_relevance": it.ai_relevance,
        }
        for it in rows
    ]


def _interest_suggestions(engine, *, embedder, k: int) -> list[dict]:
    """Intel items semantically matched to the user's interest notes."""
    interests = list_interests(engine)
    if not interests:
        return []
    from ai_intel.memory.retrieve import recall

    query = "; ".join(i["text"] for i in interests)
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
    return out


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _compose_spoken(
    news: list[dict], calendar: dict, homework: dict, suggestions: list[dict],
) -> str:
    """A short, natural-language brief — template-assembled, no LLM cost."""
    parts = [f"{_greeting()}. Here is your briefing."]
    if news:
        parts.append(f"Top story: {news[0]['title']}.")
        if len(news) > 1:
            parts.append(f"There are {len(news)} stories in your feed worth a look.")
    if calendar.get("summary"):
        parts.append(calendar["summary"])
    if homework.get("summary"):
        parts.append(homework["summary"])
    if suggestions:
        parts.append(
            "Based on your interests, you might want to read: "
            f"{suggestions[0]['title']}."
        )
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

    Returns a dict with ``news``, ``calendar``, ``homework``,
    ``suggestions``, a ``spoken`` summary string, and ``generated_at``.
    """
    # Reuse the workflow actions — they wrap the Google collectors and
    # degrade gracefully ("not connected") when there's no OAuth token.
    from ai_intel.workflows.actions.calendar import action_calendar_check
    from ai_intel.workflows.actions.classroom import action_classroom_check

    news = _top_news(engine, hours=news_hours, limit=news_limit)
    calendar = await action_calendar_check(engine, days_ahead=days_ahead)
    homework = await action_classroom_check(engine, days_ahead=days_ahead)
    suggestions = _interest_suggestions(engine, embedder=embedder, k=suggestion_limit)
    spoken = _compose_spoken(news, calendar, homework, suggestions)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
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
