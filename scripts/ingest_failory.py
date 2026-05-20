"""Ingest the failory.com Startup Cemetery into the failure_corpus.

Source: https://www.failory.com/cemetery/<slug> — each page covers one
shut-down startup with a structured "What was X?" / "Why did X fail?"
narrative (~5-8k chars of analysis per entry).

Discovery: failory's HTML listing pages only render the first ~30 entries,
but the sitemap exposes the full catalogue (~135 cemetery entries +
~299 mixed interviews as of 2026-05). We use the sitemap as the
canonical enumerator and the post body's Webflow `.w-richtext` div as
the content container.

Each row is written with:
    source         = "failure_corpus"
    classification = "post_mortem"
    author         = "Failory"
    entities_json  = {"author":"Failory", "kind":"post_mortem",
                      "company": <slug>, "outcome": "shut_down"}
    body           = full failure analysis text

Run:
    python -m scripts.ingest_failory
    python -m scripts.ingest_failory --limit 5     # dev / smoke
"""
from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree as ET

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

BASE_URL = "https://www.failory.com"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
AUTHOR = "Failory"


def fetch_cemetery_urls(client) -> list[str]:
    """Pull all /cemetery/<slug> URLs from the canonical sitemap."""
    r = client.get(SITEMAP_URL)
    r.raise_for_status()
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as exc:
        logger.error("sitemap unparseable: %s", exc)
        return []
    urls: list[str] = []
    for loc in root.iter(f"{SITEMAP_NS}loc"):
        href = (loc.text or "").strip()
        if "/cemetery/" not in href:
            continue
        if href.rstrip("/").endswith("/cemetery"):
            continue  # the index page itself
        urls.append(href)
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _slug_from_url(url: str) -> str:
    m = re.search(r"/cemetery/([^/?#]+)", url)
    return m.group(1) if m else url


def fetch_post(client, url: str) -> tuple[str, str] | None:
    """Return (title, body) or None if the page can't be parsed.

    Failory cemetery pages are Webflow-generated. The actual content
    lives inside ``.content-black-rich-text.w-richtext`` (multiple such
    divs exist on a page; the largest non-empty one is the article body).
    """
    try:
        r = client.get(url)
        r.raise_for_status()
    except Exception as exc:
        logger.warning("fetch failed for %s: %s", url, exc)
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else _slug_from_url(url)

    candidates = soup.select(".content-black-rich-text.w-richtext")
    if not candidates:
        candidates = soup.select(".w-richtext")
    body_text = ""
    if candidates:
        body_text = max(
            (c.get_text(" ", strip=False) for c in candidates),
            key=len,
            default="",
        )
    if len(body_text) < 200:
        # Fallback: largest cemetery-article div
        block = soup.select_one(".div-block-cemetery-article")
        if block is not None:
            body_text = block.get_text(" ", strip=False)
    if len(body_text) < 200:
        logger.warning("body too short for %s — skipping", url)
        return None
    body_text = clean_whitespace(body_text)
    return title, body_text


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
        slug = _slug_from_url(url)
        yield build_item(
            url=url,
            title=title,
            body=body,
            author=AUTHOR,
            kind="post_mortem",
            source="failure_corpus",
            classification="post_mortem",
            extra_entities={"company": slug, "outcome": "shut_down"},
        )


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Ingest failory.com Startup Cemetery")
    parser.add_argument("--db", default="data/items.db", help="Path to items.db")
    parser.add_argument("--limit", type=int, default=None, help="Cap entries (dev)")
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = get_engine(db_path)
    init_db(engine)

    with make_client() as client:
        logger.info("Fetching failory sitemap ...")
        urls = fetch_cemetery_urls(client)
        logger.info("Found %d cemetery URLs", len(urls))
        inserted, skipped = ingest_batch(
            engine,
            iter_posts(client, urls, args.limit),
            label="failory_cemetery",
        )
    logger.info("Done. inserted=%d skipped=%d", inserted, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
