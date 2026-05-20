"""Shared utilities for founder-brain ingesters.

These scripts run once per source (or whenever you want to refresh) and
write into the existing items.db. They reuse the Item schema so
embed_pending and recall work over the founder corpus the same way they
work over the live intel feed.

Convention for founder-brain rows:
    Item.source         = "founder_brain"
    Item.entities_json  = {"author": "Paul Graham", "kind": "essay"}
    Item.classification = "essay"
    Item.url            = canonical essay/post URL (uniqueness key)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Iterable

import httpx
from sqlmodel import Session, select

from ai_intel.db.models import Item

logger = logging.getLogger(__name__)

USER_AGENT = (
    "ai-intel-pipeline/0.1 (founder-brain ingester; +https://github.com/"
)


def make_client(timeout: float = 30.0) -> httpx.Client:
    """Conservative HTTP client: long timeout, polite UA, follow redirects."""
    return httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def throttle(seconds: float = 1.2) -> None:
    """Be a polite scraper. Call between requests."""
    time.sleep(seconds)


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def clean_whitespace(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_item(
    *,
    url: str,
    title: str,
    body: str,
    author: str,
    published_at: datetime | None = None,
    kind: str = "essay",
    source: str = "founder_brain",
    classification: str = "essay",
    extra_entities: dict | None = None,
) -> Item:
    """Construct an ingester-side Item ready for session.add().

    Defaults to the founder-brain shape (source='founder_brain',
    classification='essay'). Pass ``source='failure_corpus'`` (and
    typically ``kind='post_mortem'``, ``classification='post_mortem'``)
    when building rows for the failure corpus.
    """
    now = datetime.now(timezone.utc)
    entities: dict = {"author": author, "kind": kind}
    if extra_entities:
        entities.update(extra_entities)
    return Item(
        source=source,
        url=url,
        url_hash=url_hash(url),
        title=title,
        body=body,
        author=author,
        published_at=published_at or now,
        collected_at=now,
        classification=classification,
        entities_json=json.dumps(entities),
    )


def insert_if_new(session: Session, item: Item) -> bool:
    """Insert an Item only if no row with this URL exists yet.

    Returns True if inserted, False if already present.
    """
    existing = session.exec(
        select(Item).where(Item.url == item.url)
    ).first()
    if existing is not None:
        return False
    session.add(item)
    session.commit()
    return True


def ingest_batch(
    engine,
    items: Iterable[Item],
    *,
    label: str = "founder-brain",
) -> tuple[int, int]:
    """Insert a stream of Items idempotently. Returns (inserted, skipped)."""
    inserted = skipped = 0
    with Session(engine) as session:
        for it in items:
            if insert_if_new(session, it):
                inserted += 1
            else:
                skipped += 1
    logger.info("%s: inserted=%d skipped=%d", label, inserted, skipped)
    return inserted, skipped
