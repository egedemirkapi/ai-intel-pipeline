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
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterator

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
ATOM_URL = f"{BASE_URL}/posts.atom"
ATOM_NS = "{http://www.w3.org/2005/Atom}"
AUTHOR = "Sam Altman"


def fetch_archive_links(client, max_pages: int = 20) -> list[str]:
    """Return absolute URLs of every Altman blog post.

    Posthaven's HTML archive is JS-rendered via Algolia and serves no
    post links in the static markup, but the Atom feed at
    ``/posts.atom`` is paginated and gives 30 entries per page. Walking
    ``?page=1..N`` until a page returns 0 entries reliably enumerates
    the full archive (~121 posts as of 2026-05).
    """
    seen: set[str] = set()
    out: list[str] = []
    for page in range(1, max_pages + 1):
        url = f"{ATOM_URL}?page={page}"
        try:
            r = client.get(url)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("Atom page %d failed: %s — stopping", page, exc)
            break
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as exc:
            logger.warning("Atom page %d unparseable: %s — stopping", page, exc)
            break
        entries = root.findall(f"{ATOM_NS}entry")
        new_on_page = 0
        for entry in entries:
            link = entry.find(f"{ATOM_NS}link")
            if link is None:
                continue
            href = (link.get("href") or "").strip()
            if not href.startswith(BASE_URL):
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append(href)
            new_on_page += 1
        if new_on_page == 0:
            break
        if page > 1:
            throttle()
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
