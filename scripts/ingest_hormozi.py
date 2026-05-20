"""Ingest Alex Hormozi content into the founder_brain corpus.

STATUS: deferred — site changed; only YouTube remains (probed 2026-05-19).

Original plan: scrape acquisition.com/blog. As of 2026-05, that site
has been re-organized into a paid education platform. Its sitemap
contains 621 URLs covering courses, workshops, and training modules
(`/training/money/...`, `/workshop-framework`, `/journal-25`, etc.)
— but `/blog/` itself returns 404 and zero sitemap URLs match `/blog/`.
There is no longer a public Hormozi blog.

Hormozi's actually-public content (besides his copyrighted books, which
are out of scope) lives entirely on:
- YouTube (@AlexHormozi channel) — long-form business breakdowns
- @AlexHormozi podcast — same content as the YouTube audio
- Twitter/X — short-form takes

Realistic path forward:
- `yt-dlp --skip-download --write-auto-sub --sub-lang en` against the
  @AlexHormozi channel → VTT auto-captions per video → strip timestamps
  → concatenate into prose. ~500 videos × ~30 min = ~250 hours of
  transcripts. Quality lower than hand-edited prose (ASR errors,
  conversational filler).
- Tag entities_json={"author":"Alex Hormozi","kind":"podcast_transcript",
  "video_id":<yt id>, "duration_s":...}.

In the meantime, `src/ai_intel/personas/alex_hormozi.md` is hand-distilled
from public Hormozi material (offer construction, unit economics,
lead generation). Worth noting: it's been the most-discriminating
critic in practice — wider 38-72 score range than other personas
across recent candidates. So the missing body corpus is not currently
a quality blocker for the evaluator.

Run:
    python -m scripts.ingest_hormozi
"""
from __future__ import annotations

import logging

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_hormozi.py is deferred — see top of file.\n"
        "  TL;DR: acquisition.com is now a paid course site, no blog.\n"
        "  Free public content is on YouTube — would need yt-dlp +\n"
        "  caption transcripts. Books are copyrighted.\n"
        "  alex_hormozi persona at src/ai_intel/personas/alex_hormozi.md\n"
        "  is functional meanwhile (most discriminating critic)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
