"""Action: check Google Calendar for upcoming events.

Wraps GoogleCalendarCollector for a live fetch + builds a short
human-readable summary the ``notify`` action can surface.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def action_calendar_check(engine, *, days_ahead: int = 7) -> dict:
    """Fetch upcoming calendar events for the next ``days_ahead`` days.

    Returns the events plus a one-line ``summary`` suitable for a
    desktop notification.
    """
    from ai_intel.collectors.google_calendar import GoogleCalendarCollector
    from ai_intel.google_auth import has_token

    if not has_token():
        return {
            "error": "Google not connected — run scripts/setup_google_auth.py",
            "summary": "Calendar unavailable (Google not connected)",
            "events": [],
        }

    collector = GoogleCalendarCollector(days_ahead=days_ahead)
    raw = await collector.fetch_since(datetime.now(timezone.utc))

    events = []
    for it in raw:
        meta = it.raw or {}
        events.append({
            "title": it.title,
            "start": meta.get("start"),
            "location": meta.get("location"),
        })

    if events:
        summary = (
            f"{len(events)} event(s) in the next {days_ahead} days: "
            + "; ".join(f"{e['title']} ({e['start']})" for e in events[:5])
        )
    else:
        summary = f"Nothing on the calendar in the next {days_ahead} days."

    return {"events": events, "count": len(events), "summary": summary}
