"""Ingest Paul Graham essays into the founder_brain corpus.

Source: http://paulgraham.com/articles.html (the master index).
Each essay is a separate HTML page at paulgraham.com/<slug>.html.

The HTML is old-school: a <table> layout with a <font> blob holding the
essay text. We pull the <body> minus boilerplate (image header + footer
nav links) and feed it as the Item body.

Run idempotently:
    python -m scripts.ingest_pg
    python -m scripts.ingest_pg --db data/items.db --limit 5  # dev
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ai_intel.db.session import get_engine, init_db
from ai_intel.logging_config import setup_logging
from scripts._common import (
    build_item,
    clean_whitespace,
    ingest_batch,
    make_client,
    throttle,
)

logger = logging.getLogger(__name__)

INDEX_URL = "http://paulgraham.com/articles.html"
AUTHOR = "Paul Graham"

# Boilerplate links the index page has alongside essay links.
# These end in .html but are nav, not essays.
_NON_ESSAY_SLUGS = {
    "articles.html",
    "index.html",
    "rss.html",
    "lists.html",
    "rfs.html",
    "books.html",
    "kedrosky.html",  # external/redirect-style
    "bio.html",
}


def fetch_index(client) -> list[tuple[str, str]]:
    """Return [(essay_title, absolute_url), ...] from articles.html."""
    r = client.get(INDEX_URL)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        if not text or not href.endswith(".html"):
            continue
        if href.startswith("http://") or href.startswith("https://"):
            # External link — skip
            continue
        if href in _NON_ESSAY_SLUGS:
            continue
        absolute = urljoin(INDEX_URL, href)
        out.append((text, absolute))
    # Dedupe preserving order (some essays linked twice)
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for title, url in out:
        if url in seen:
            continue
        seen.add(url)
        uniq.append((title, url))
    return uniq


def fetch_essay(client, url: str) -> tuple[str, str] | None:
    """Return (title, body) or None if fetch / parse fails."""
    try:
        r = client.get(url)
        r.raise_for_status()
    except Exception as exc:
        logger.warning("fetch failed for %s: %s", url, exc)
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    # Title: <title>...</title>
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else url
    # Body: largest text-bearing <font> tag (typical PG layout).
    # Fall back to whole <body> stripped.
    candidates = soup.find_all("font")
    body_text = ""
    if candidates:
        body_text = max(
            (c.get_text(" ", strip=False) for c in candidates),
            key=len,
            default="",
        )
    if len(body_text) < 200 and soup.body is not None:
        body_text = soup.body.get_text(" ", strip=False)
    body_text = clean_whitespace(body_text)
    if len(body_text) < 200:
        logger.warning("body too short for %s — skipping", url)
        return None
    return title, body_text


def iter_essays(client, urls: list[tuple[str, str]], limit: int | None) -> Iterator:
    for i, (title, url) in enumerate(urls):
        if limit is not None and i >= limit:
            break
        if i > 0:
            throttle()
        fetched = fetch_essay(client, url)
        if fetched is None:
            continue
        real_title, body = fetched
        # Prefer the <title> if it's non-empty and not just the homepage title.
        use_title = real_title if real_title and "Paul Graham" not in real_title else title
        yield build_item(
            url=url,
            title=use_title,
            body=body,
            author=AUTHOR,
            kind="essay",
        )


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Ingest Paul Graham essays")
    parser.add_argument("--db", default="data/items.db", help="Path to items.db")
    parser.add_argument("--limit", type=int, default=None, help="Cap essays (dev)")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(db_path)
    init_db(engine)

    with make_client() as client:
        logger.info("Fetching PG index from %s ...", INDEX_URL)
        urls = fetch_index(client)
        logger.info("Found %d essays on index", len(urls))
        inserted, skipped = ingest_batch(
            engine,
            iter_essays(client, urls, args.limit),
            label="paul_graham",
        )
    logger.info("Done. inserted=%d skipped=%d", inserted, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
