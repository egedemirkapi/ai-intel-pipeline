"""Gmail collector — recent thread metadata + snippets as Items.

Read-only (gmail.readonly). Pulls recent messages from the inbox —
subject, sender, snippet. NOT full bodies (privacy + volume): the
snippet Gmail returns is enough for "did I get anything important".

Each message → RawItem:
    title  = subject
    body   = from + date + snippet
    url    = a gmail deep link by message id
    source = "gmail"

Privacy note: only the Gmail-provided ~100-char snippet is stored,
never full message bodies or attachments. Even the snippet stays on
the local machine (items.db).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)


def _header(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _message_to_item(msg: dict) -> RawItem:
    headers = msg.get("payload", {}).get("headers", [])
    subject = _header(headers, "Subject") or "(no subject)"
    sender = _header(headers, "From") or "(unknown)"
    date_hdr = _header(headers, "Date")
    snippet = msg.get("snippet", "")
    msg_id = msg.get("id", "")
    url = f"https://mail.google.com/mail/u/0/#inbox/{msg_id}"

    # internalDate is epoch ms
    try:
        published = datetime.fromtimestamp(
            int(msg.get("internalDate", "0")) / 1000.0, tz=timezone.utc,
        )
    except (ValueError, TypeError):
        published = datetime.now(timezone.utc)

    body = f"From: {sender}\nDate: {date_hdr}\n\n{snippet}"
    return RawItem(
        url=url,
        title=f"[Email] {subject}",
        published_at=published,
        body=body,
        author=sender,
        raw={"kind": "email", "message_id": msg_id, "sender": sender},
    )


class GoogleGmailCollector(Collector):
    """Fetch recent inbox messages (metadata + snippet only)."""

    name = "gmail"

    def __init__(self, *, max_messages: int = 25, query: str = "in:inbox") -> None:
        self.max_messages = max_messages
        self.query = query

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        from ai_intel.google_auth import build_service, has_token

        if not has_token():
            logger.warning("gmail: no Google token — skipping.")
            return []
        try:
            service = build_service("gmail", "v1")
        except Exception as exc:
            logger.error("gmail: could not build service: %s", exc)
            return []

        try:
            listing = (
                service.users()
                .messages()
                .list(userId="me", q=self.query, maxResults=self.max_messages)
                .execute()
            )
        except Exception as exc:
            logger.error("gmail: messages().list failed: %s", exc)
            return []

        items: list[RawItem] = []
        for ref in listing.get("messages", []):
            mid = ref.get("id")
            if not mid:
                continue
            try:
                # metadata format = headers + snippet, NOT full body
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me", id=mid, format="metadata",
                        metadataHeaders=["Subject", "From", "Date"],
                    )
                    .execute()
                )
                items.append(_message_to_item(msg))
            except Exception as exc:
                logger.warning("gmail: get message %s failed: %s", mid, exc)

        logger.info("gmail: collected %d messages", len(items))
        return items
