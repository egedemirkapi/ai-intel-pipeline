"""Ingest Y Combinator library + Startup School notes into founder_brain.

STATUS: stub.

Two sources:

1. **ycombinator.com/library** — curated essays + advice docs from YC
   partners (Michael Seibel, Jessica Livingston, Paul Graham, etc.).
   Static HTML, indexed by topic.

2. **startupschool.org/library** — Startup School notes / lecture notes
   (requires login for some content; only ingest publicly-listed
   resources). Lectures themselves are on YouTube — use yt-dlp for
   transcripts as a follow-up.

Implementation:
- author per item = partner who wrote/spoke it (extract from byline)
- kind = "essay" | "lecture_transcript" | "guide"
- entities_json.org = "Y Combinator"
- Many YC library entries cross-reference PG essays — dedupe by URL.

Persona (Phase 5c): a generic "yc_partner" persona captures the YC
playbook (do things that don't scale, make something people want,
talk to users). Specific partners not split out for v1.

Run (today, prints a friendly message):
    python -m scripts.ingest_yc
"""
from __future__ import annotations

import logging
import sys

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_yc.py is a stub.\n"
        "  Sources: ycombinator.com/library (HTML), startupschool.org/library "
        "(some public). Lectures via yt-dlp.\n"
        "  Dedup against PG essays already ingested."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
