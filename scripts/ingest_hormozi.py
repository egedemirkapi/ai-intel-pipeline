"""Ingest Alex Hormozi public content into the founder_brain corpus.

STATUS: stub.

Three legal-to-scrape sources:

1. **acquisition.com/blog** — public blog posts. The Webflow-rendered
   pages have clean <article> sections; reuse the pattern in
   ``scripts/ingest_altman.py``.

2. **YouTube — Alex Hormozi channel** — short and long-form videos.
   Use ``yt-dlp --skip-download --write-auto-sub --sub-lang en`` for
   auto-captions; merge .vtt lines into prose; tag each as
   kind="video_transcript".

3. **acquisition.com/training** (free resources, NOT the paid courses)
   if any are gated public.

DO NOT scrape:
- The $100M Offers / $100M Leads books (copyrighted).
- Any acquisition.com community content (members-only).
- Paid Skool group posts.

Implementation pattern: identical to ingest_altman.py. author = "Alex
Hormozi"; kind = "blog_post" | "video_transcript".

Run (today):
    python -m scripts.ingest_hormozi
"""
from __future__ import annotations

import logging
import sys

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_hormozi.py is a stub. Pattern matches ingest_altman.py.\n"
        "  Sources: acquisition.com/blog (HTML), youtube.com/@AlexHormozi "
        "(transcripts via yt-dlp).\n"
        "  DO NOT scrape the books — copyrighted."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
