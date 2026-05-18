"""Ingest a16z partner essays into the founder_brain corpus.

STATUS: stub.

Source: https://a16z.com/articles/ (the public essay index, partner
bylines included). The site is Next.js-rendered but the HTML response
includes the essay body in the initial payload (no JS required).

Implementation outline:
1. GET https://a16z.com/articles/?page=1..N (paginate until 404 or empty)
2. For each link found in the article listing, fetch the page
3. Parse <article> body; extract byline from <p class="author"> or JSON-LD
4. build_item(author=byline, source=founder_brain, kind="essay",
   entities_json={"author": byline, "org": "a16z", "kind": "essay"})

The author tag is per-essay (Marc Andreessen, Ben Horowitz, Chris Dixon,
Connie Chan, Andrew Chen, etc.). Personas (Phase 5c) include a generic
"a16z" file that captures their shared lens (markets, networks effects,
zero-to-one) — but specific partners can be split out later if useful.

Run (today, prints a friendly message):
    python -m scripts.ingest_a16z
"""
from __future__ import annotations

import logging
import sys

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_a16z.py is a stub.\n"
        "  Source: https://a16z.com/articles/  (paginated, server-rendered).\n"
        "  Follow ingest_altman.py pattern for HTML parsing."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
