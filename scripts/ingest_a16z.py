"""Ingest a16z partner essays into the founder_brain corpus.

Source: a16z.com runs WordPress with Yoast SEO sitemaps. The article
catalogue is split into three post-sitemaps:
    /post-sitemap.xml   (~198 URLs)
    /post-sitemap2.xml  (~455 URLs)
    /post-sitemap3.xml  (~30 URLs, newest)
Total ~683 articles as of 2026-05.

Each post page renders the full body in `<main>` — no JS required.
Byline is extracted from the WordPress author span when present.

Run:
    python -m scripts.ingest_a16z
    python -m scripts.ingest_a16z --limit 10   # dev / smoke
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

BASE_URL = "https://a16z.com"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
DEFAULT_AUTHOR = "a16z"
# Skip categories that aren't partner-essay content. These slugs appear
# in post-sitemaps but are press/news/event detail pages, not essays.
_SKIP_PATTERNS = (
    "/news-content/",
    "/disclosures/",
    "/privacy-policy/",
    "/cookie-policy/",
    "/methodology/",
)


def fetch_archive_links(client, max_sitemaps: int = 6) -> list[str]:
    """Walk Yoast post-sitemaps and return all article URLs."""
    out: list[str] = []
    seen: set[str] = set()
    for n in range(1, max_sitemaps + 1):
        sm_url = f"{BASE_URL}/post-sitemap{'' if n == 1 else n}.xml"
        try:
            r = client.get(sm_url)
            r.raise_for_status()
        except Exception:
            break  # Past the last sitemap
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError as exc:
            logger.warning("sitemap %s unparseable: %s", sm_url, exc)
            break
        urls = root.findall(f"{SITEMAP_NS}url/{SITEMAP_NS}loc")
        new_on_page = 0
        for u in urls:
            href = (u.text or "").strip()
            if not href.startswith(BASE_URL):
                continue
            if any(skip in href for skip in _SKIP_PATTERNS):
                continue
            if href in seen:
                continue
            seen.add(href)
            out.append(href)
            new_on_page += 1
        if new_on_page == 0:
            break
        if n > 1:
            throttle()
    return out


def _extract_author(soup: BeautifulSoup) -> str:
    """Pull the byline from WordPress markup. Falls back to 'a16z'."""
    for sel in [
        "span.author a", ".author-name", '[rel="author"]',
        '[itemprop="author"]', "address.byline a",
    ]:
        node = soup.select_one(sel)
        if node:
            name = node.get_text(strip=True)
            if name:
                return name[:80]
    return DEFAULT_AUTHOR


def fetch_post(client, url: str) -> tuple[str, str, str] | None:
    """Return (title, body, author) or None if fetch / parse fails."""
    try:
        r = client.get(url)
        r.raise_for_status()
    except Exception as exc:
        logger.warning("fetch failed for %s: %s", url, exc)
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else url
    body_node = soup.find("main") or soup.find("article") or soup.body
    if body_node is None:
        return None
    text = clean_whitespace(body_node.get_text(" ", strip=False))
    if len(text) < 300:
        logger.warning("body too short for %s — skipping", url)
        return None
    author = _extract_author(soup)
    return title, text, author


def iter_posts(client, urls: list[str], limit: int | None) -> Iterator:
    for i, url in enumerate(urls):
        if limit is not None and i >= limit:
            break
        if i > 0:
            throttle()
        fetched = fetch_post(client, url)
        if fetched is None:
            continue
        title, body, author = fetched
        yield build_item(
            url=url,
            title=title,
            body=body,
            author=author,
            kind="essay",
            extra_entities={"org": "a16z"},
        )


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Ingest a16z partner essays")
    parser.add_argument("--db", default="data/items.db", help="Path to items.db")
    parser.add_argument("--limit", type=int, default=None, help="Cap essays (dev)")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(db_path)
    init_db(engine)

    with make_client() as client:
        logger.info("Fetching a16z post-sitemaps ...")
        urls = fetch_archive_links(client)
        logger.info("Found %d a16z article URLs", len(urls))
        inserted, skipped = ingest_batch(
            engine,
            iter_posts(client, urls, args.limit),
            label="a16z",
        )
    logger.info("Done. inserted=%d skipped=%d", inserted, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
