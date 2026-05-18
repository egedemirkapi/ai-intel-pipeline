"""Ingest YC-backed startup shutdown threads into failure_corpus.

STATUS: stub.

YC has no official "graveyard" page. The signal lives in two places:

1. **Twitter shutdown threads** — founders writing "We're shutting down
   ${company}. Here's what we learned." Search query: from YC founders +
   keywords "shutting down", "post-mortem", "winding down".
   - The cleanest path is the YC Founder Directory (semi-public) +
     a search of those handles. NOT trivial to automate.
2. **HN "Show HN: <YC company> is shutting down"** posts — already in
   the items.db via the existing HN collector. A specialized
   collector could just FILTER existing Items for title patterns and
   re-tag them.

Quick win: add a tag-pass over existing HN items that:
- title contains "shutting down" OR "post mortem" OR "wind down"
- mark these as also source="failure_corpus" via a separate tag table,
  so they show in both feeds.

Run (today):
    python -m scripts.ingest_yc_graveyard
"""
from __future__ import annotations

import logging
import sys

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_yc_graveyard.py is a stub.\n"
        "  No official YC graveyard page. Two paths:\n"
        "    1) Filter existing HN items matching shutdown patterns\n"
        "    2) Scrape Twitter shutdown threads (rate-limited; needs auth)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
