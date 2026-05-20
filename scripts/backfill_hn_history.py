"""Backfill ~60 days of Hacker News history so the trajectory picker
has real longitudinal mention counts to work with.

Without this, the proposer's trajectory picker (`_pick_tech_signal`)
falls back to cold-start mode because the DB only contains the last
few days of collected items. The picker's novelty × momentum math
needs ≥60 days of history to be meaningful.

Source: HN Algolia API
  https://hn.algolia.com/api/v1/search_by_date
Free, no key required, no documented rate limit (we throttle politely).

Each story is inserted as an Item with:
  source         = "hn"
  url            = canonical HN discussion URL (stable, unique)
  title          = the story title
  body           = story_text if present, else falls back to title
  author         = HN username
  published_at   = HN's created_at (real publication time)
  collected_at   = HN's created_at (REUSED — preserves real chronology
                   so the trajectory math sees historical timestamps)

We bound volume per 7-day window (default 200 stories/week) so backfill
finishes in minutes and we don't drown the enrichment pipeline.

Run:
    python scripts/backfill_hn_history.py
    python scripts/backfill_hn_history.py --days 60 --per-window 200
    python scripts/backfill_hn_history.py --days 14 --min-points 50   # quick test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlmodel import Session, select

from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db
from ai_intel.logging_config import setup_logging
from scripts._common import make_client, throttle

logger = logging.getLogger(__name__)

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"


def _hn_url(object_id: str) -> str:
    return f"https://news.ycombinator.com/item?id={object_id}"


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]


def _existing_url_hashes(engine, hashes: set[str]) -> set[str]:
    """Return the subset of ``hashes`` that already have a row in Item."""
    if not hashes:
        return set()
    with Session(engine) as s:
        rows = list(s.exec(
            select(Item.url_hash).where(Item.url_hash.in_(hashes))
        ))
    return {row for row in rows}


def fetch_window(
    client: httpx.Client,
    *,
    start_ts: int,
    end_ts: int,
    min_points: int,
    per_window: int,
) -> list[dict]:
    """Pull stories from one [start_ts, end_ts) window via Algolia.

    Loops pages until we hit ``per_window`` or the API returns no more
    hits. Algolia max hitsPerPage is 1000 but in practice we cap each
    page lower to be polite.
    """
    out: list[dict] = []
    hits_per_page = min(per_window, 200)
    for page in range(0, 20):  # safety upper bound; very unlikely to hit
        params = {
            "tags": "story",
            "numericFilters": (
                f"created_at_i>={start_ts},created_at_i<{end_ts},"
                f"points>{min_points}"
            ),
            "hitsPerPage": hits_per_page,
            "page": page,
        }
        try:
            r = client.get(ALGOLIA_URL, params=params)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("HN Algolia request failed: %s", exc)
            break
        data = r.json()
        hits = data.get("hits") or []
        if not hits:
            break
        out.extend(hits)
        if len(out) >= per_window:
            out = out[:per_window]
            break
        # Algolia signals more pages via nbPages, but page=0 + len(hits)<hitsPerPage also works
        if len(hits) < hits_per_page:
            break
        throttle(0.4)  # polite between pages
    return out


def hit_to_item(hit: dict) -> Item | None:
    """Construct an Item from one Algolia hit, or None if malformed."""
    object_id = str(hit.get("objectID") or "").strip()
    title = (hit.get("title") or "").strip()
    if not object_id or not title:
        return None
    created_at_i = hit.get("created_at_i")
    if not isinstance(created_at_i, (int, float)):
        return None
    when = datetime.fromtimestamp(int(created_at_i), tz=timezone.utc)
    url = _hn_url(object_id)
    body = (hit.get("story_text") or "").strip()
    if not body:
        # If no story text, embed the external URL into the body so
        # the proposer's context format isn't blank
        ext = (hit.get("url") or "").strip()
        body = f"(no story text){' link: ' + ext if ext else ''}"
    return Item(
        source="hn",
        url=url,
        url_hash=_url_hash(url),
        title=title[:512],
        body=body[:4000],
        author=(hit.get("author") or None),
        published_at=when,
        collected_at=when,       # historical timestamp, NOT now
        raw_json=json.dumps({
            "object_id": object_id,
            "points": hit.get("points"),
            "num_comments": hit.get("num_comments"),
            "external_url": hit.get("url"),
        }),
    )


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Backfill HN history via Algolia")
    parser.add_argument("--db", default="data/items.db")
    parser.add_argument("--days", type=int, default=60,
                        help="How many days back to backfill (default 60)")
    parser.add_argument("--per-window", type=int, default=200,
                        help="Max stories per 7-day window (default 200)")
    parser.add_argument("--min-points", type=int, default=20,
                        help="Karma floor for stories (default 20)")
    args = parser.parse_args(argv)

    engine = get_engine(Path(args.db))
    init_db(engine)

    now = datetime.now(timezone.utc)
    # Walk backward from today in 7-day windows
    inserted = 0
    skipped = 0
    fetched = 0

    with make_client() as client:
        for week_offset in range(0, max(1, args.days // 7 + 1)):
            end = now - timedelta(days=week_offset * 7)
            start = end - timedelta(days=7)
            if (now - start).days > args.days:
                start = now - timedelta(days=args.days)
            start_ts = int(start.timestamp())
            end_ts = int(end.timestamp())
            if start_ts >= end_ts:
                break

            logger.info(
                "Backfilling HN window [%s, %s) (week_offset=%d)",
                start.date(), end.date(), week_offset,
            )
            hits = fetch_window(
                client,
                start_ts=start_ts, end_ts=end_ts,
                min_points=args.min_points,
                per_window=args.per_window,
            )
            fetched += len(hits)
            if not hits:
                continue

            # Idempotent insert: pre-load existing url_hashes in this batch
            items = [it for it in (hit_to_item(h) for h in hits) if it is not None]
            hashes = {it.url_hash for it in items}
            already = _existing_url_hashes(engine, hashes)
            new_items = [it for it in items if it.url_hash not in already]
            skipped += len(items) - len(new_items)

            if new_items:
                with Session(engine) as s:
                    for it in new_items:
                        s.add(it)
                    s.commit()
                inserted += len(new_items)

            throttle(0.6)  # polite between windows

    logger.info(
        "Done. fetched=%d inserted=%d skipped(already in DB)=%d",
        fetched, inserted, skipped,
    )
    print(f"HN backfill: fetched={fetched} inserted={inserted} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
