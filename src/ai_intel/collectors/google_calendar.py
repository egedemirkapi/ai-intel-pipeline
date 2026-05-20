"""Google Calendar collector — upcoming events as Items.

Powers "what's on my calendar tomorrow?". Read-only
(calendar.readonly). Pulls events from now forward (default 14 days)
on the primary calendar.

Each event → RawItem:
    title  = event summary
    body   = start/end + location + description
    url    = htmlLink
    source = "gcalendar"
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)


def _event_time(node: dict) -> tuple[str, datetime]:
    """Return (display_string, datetime). Handles all-day vs timed events."""
    if "dateTime" in node:
        raw = node["dateTime"]
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.now(timezone.utc)
        return raw, dt
    if "date" in node:  # all-day event
        raw = node["date"]
        try:
            dt = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        except ValueError:
            dt = datetime.now(timezone.utc)
        return f"{raw} (all day)", dt
    return "(unknown)", datetime.now(timezone.utc)


def _event_to_item(ev: dict) -> RawItem:
    summary = ev.get("summary", "(no title)")
    start_str, start_dt = _event_time(ev.get("start", {}))
    end_str, _ = _event_time(ev.get("end", {}))
    location = ev.get("location", "")
    description = ev.get("description", "")
    url = ev.get("htmlLink") or f"gcalendar-event://{ev.get('id', '')}"

    body_lines = [f"Start: {start_str}", f"End: {end_str}"]
    if location:
        body_lines.append(f"Location: {location}")
    if description:
        body_lines.append("")
        body_lines.append(description)

    return RawItem(
        url=url,
        title=f"[Calendar] {summary}",
        published_at=start_dt,
        body="\n".join(body_lines),
        author=ev.get("organizer", {}).get("displayName") or "Calendar",
        raw={
            "kind": "calendar_event",
            "event_id": ev.get("id"),
            "start": start_str,
            "end": end_str,
            "location": location,
        },
    )


class GoogleCalendarCollector(Collector):
    """Fetch upcoming primary-calendar events as RawItems."""

    name = "gcalendar"

    def __init__(self, *, days_ahead: int = 14, max_events: int = 100) -> None:
        self.days_ahead = days_ahead
        self.max_events = max_events

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        from ai_intel.google_auth import build_service, has_token

        if not has_token():
            logger.warning("gcalendar: no Google token — skipping.")
            return []
        try:
            service = build_service("calendar", "v3")
        except Exception as exc:
            logger.error("gcalendar: could not build service: %s", exc)
            return []

        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=self.days_ahead)).isoformat()

        try:
            resp = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=self.max_events,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        except Exception as exc:
            logger.error("gcalendar: events().list failed: %s", exc)
            return []

        items = [_event_to_item(ev) for ev in resp.get("items", [])]
        logger.info("gcalendar: collected %d events", len(items))
        return items
