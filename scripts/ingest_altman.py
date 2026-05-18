"""Ingest Sam Altman blog posts into the founder_brain corpus.

Source: https://blog.samaltman.com/archive (chronological index).
Each post is at blog.samaltman.com/<slug>.

The blog is Posthaven-based; HTML is straightforward. We walk the
archive page for post URLs then fetch each.
"""
from __future__ import annotations

import argparse
import logging
import re
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

BASE_URL = "https://blog.samaltman.com"
ARCHIVE_URL = f"{BASE_URL}/archive"
AUTHOR = "Sam Altman"


def fetch_archive_links(client) -> list[str]:
    """Return absolute URLs of every blog post in the archive."""
    r = client.get(ARCHIVE_URL)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        # Posthaven post URLs follow /<slug> where slug != archive/page/feed
        # and typically contain a hyphen or year-like marker.
        if href.startswith("http"):
            if not href.startswith(BASE_URL):
                continue
            path = href[len(BASE_URL):]
        else:
            path = href
        if path in ("", "/", "/archive", "/feed", "/about"):
            continue
        if re.match(r"^/(archive|feed|about|page|tag|category)(/|$)", path):
            continue
        if not path.startswith("/"):
            continue
        # Looks like a post slug
        urls.append(urljoin(BASE_URL, path))
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def fetch_post(client, url: str) -> tuple[str, str] | None:
    try:
        r = client.get(url)
        r.raise_for_status()
    except Exception as exc:
        logger.warning("fetch failed for %s: %s", url, exc)
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    # Title: try <h1> first, then <title>
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        t = soup.find("title")
        title = t.get_text(strip=True) if t else url
    # Body: Posthaven wraps posts in <div class="posthaven-post-body"> or
    # similar; fall back to <article> or main text content.
    body_node = (
        soup.find("div", class_=re.compile(r"posthaven.*body"))
        or soup.find("article")
        or soup.find("main")
        or soup.body
    )
    if body_node is None:
        return None
    text = clean_whitespace(body_node.get_text(" ", strip=False))
    if len(text) < 200:
        logger.warning("body too short for %s — skipping", url)
        return None
    return title, text


def iter_posts(client, urls: list[str], limit: int | None) -> Iterator:
    for i, url in enumerate(urls):
        if limit is not None and i >= limit:
            break
        if i > 0:
            throttle()
        fetched = fetch_post(client, url)
        if fetched is None:
            continue
        title, body = fetched
        yield build_item(
            url=url,
            title=title,
            body=body,
            author=AUTHOR,
            kind="blog_post",
        )


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Ingest Sam Altman blog")
    parser.add_argument("--db", default="data/items.db", help="Path to items.db")
    parser.add_argument("--limit", type=int, default=None, help="Cap posts (dev)")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(db_path)
    init_db(engine)

    with make_client() as client:
        logger.info("Fetching Altman archive ...")
        urls = fetch_archive_links(client)
        logger.info("Found %d candidate post URLs", len(urls))
        inserted, skipped = ingest_batch(
            engine,
            iter_posts(client, urls, args.limit),
            label="sam_altman",
        )
    logger.info("Done. inserted=%d skipped=%d", inserted, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
