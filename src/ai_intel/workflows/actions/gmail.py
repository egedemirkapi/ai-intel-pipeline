"""Action: check Gmail for recent inbox messages.

Wraps GoogleGmailCollector for a live fetch + builds a short
human-readable summary the ``notify`` action can surface. Reads
metadata + snippet only — never full message bodies.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def action_email_check(engine, *, max_messages: int = 15) -> dict:
    """Fetch recent inbox messages.

    Returns the messages plus a one-line ``summary`` suitable for a
    desktop notification.
    """
    from ai_intel.collectors.google_gmail import GoogleGmailCollector
    from ai_intel.google_auth import has_token

    if not has_token():
        return {
            "error": "Google not connected — run scripts/setup_google_auth.py",
            "summary": "Email unavailable (Google not connected)",
            "messages": [],
        }

    collector = GoogleGmailCollector(max_messages=max_messages)
    raw = await collector.fetch_since(datetime.now(timezone.utc))

    messages = []
    for it in raw:
        meta = it.raw or {}
        messages.append({
            "subject": it.title,
            "from": meta.get("sender"),
        })

    if messages:
        summary = (
            f"{len(messages)} recent message(s): "
            + "; ".join(m["subject"] for m in messages[:5])
        )
    else:
        summary = "No recent messages in the inbox."

    return {"messages": messages, "count": len(messages), "summary": summary}
