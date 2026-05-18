"""Ingest Garry Tan content into the founder_brain corpus.

STATUS: stub. The two practical content sources for Garry Tan are:

1. **garrytan.substack.com** — has an archive view but uses dynamic
   loading. RSS feed at garrytan.substack.com/feed is the cleanest entry
   (returns recent posts only — Substack caps RSS to ~20 latest).
2. **YouTube — Garry Tan's channel** — long-form interviews with founders.
   Best fetched via ``yt-dlp --skip-download --write-auto-sub --sub-lang en``
   per video, then converting the .vtt subtitles into plain text.

Implementation notes for when you fill this in:
- Use the same scripts/_common.py helpers (build_item, ingest_batch).
- author = "Garry Tan"; kind = "post" or "video_transcript".
- For YouTube transcripts, set url to the video URL and body to the
  cleaned-up subtitle text.
- yt-dlp is NOT in this project's dependencies. Add via ``pip install
  yt-dlp`` in the venv used to run this script.

Run (today, prints a friendly message):
    python -m scripts.ingest_tan
"""
from __future__ import annotations

import logging
import sys

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_tan.py is a stub. Two sources to wire up:\n"
        "  1) https://garrytan.substack.com/feed  (RSS, capped to ~20)\n"
        "  2) youtube.com/@garrytan  (use yt-dlp --skip-download "
        "--write-auto-sub for transcripts)\n"
        "See scripts/ingest_pg.py for the pattern."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
