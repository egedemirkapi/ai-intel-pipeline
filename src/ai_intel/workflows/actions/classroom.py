"""Action: check Google Classroom for upcoming coursework.

Wraps GoogleClassroomCollector for a live fetch + builds a short
human-readable summary the ``notify`` action can surface.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _within_window(due_iso: str | None, days_ahead: int) -> bool:
    if not due_iso:
        return False
    try:
        due = datetime.fromisoformat(due_iso)
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    now = datetime.now(timezone.utc)
    return now <= due <= now + timedelta(days=days_ahead)


async def action_classroom_check(engine, *, days_ahead: int = 7) -> dict:
    """Fetch Classroom coursework, filter to the next ``days_ahead`` days.

    Returns a dict with the filtered assignments and a one-line
    ``summary`` suitable for a desktop notification.
    """
    from ai_intel.collectors.google_classroom import GoogleClassroomCollector
    from ai_intel.google_auth import has_token

    if not has_token():
        return {
            "error": "Google not connected — run scripts/setup_google_auth.py",
            "summary": "Classroom unavailable (Google not connected)",
            "assignments": [],
        }

    collector = GoogleClassroomCollector()
    raw = await collector.fetch_since(datetime.now(timezone.utc) - timedelta(days=1))

    upcoming = []
    for it in raw:
        meta = it.raw or {}
        if meta.get("kind") != "assignment":
            continue
        due = meta.get("due_date")
        if _within_window(due, days_ahead):
            upcoming.append({
                "title": it.title,
                "course": meta.get("course"),
                "due_date": due,
            })
    upcoming.sort(key=lambda a: a["due_date"] or "")

    if upcoming:
        summary = (
            f"{len(upcoming)} assignment(s) due in the next {days_ahead} days: "
            + "; ".join(f"{a['title']} ({a['due_date'][:10]})" for a in upcoming[:5])
        )
    else:
        summary = f"Nothing due in the next {days_ahead} days."

    return {
        "assignments": upcoming,
        "count": len(upcoming),
        "summary": summary,
    }
