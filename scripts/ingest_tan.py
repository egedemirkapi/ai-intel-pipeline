"""Ingest Garry Tan content into the founder_brain corpus.

STATUS: deferred — no public text blog exists (probed 2026-05-19).

Sources probed and what we found:
- https://garrytan.com           → DNS does not resolve
- https://www.garrytan.com       → DNS does not resolve
- https://garrytan.substack.com  → 404 (no substack at this slug)
- https://garrytan.substack.com/feed → 404

Garry Tan's public content as of 2026-05 lives in:
- YouTube channel "Garry Tan" — daily "What's Hot in Tech", founder
  office hours, startup advice videos
- Twitter/X (@garrytan) — short-form takes, founder advice threads
- Some YC `/library/` interviews feature him (but `/library/` is itself
  React-rendered — see ingest_yc.py for that blocker)

Realistic path forward, pick one or combine:
1. **yt-dlp + auto-captions on his YouTube channel** (most leverage).
   Same approach as deferred Hormozi ingest. 1k+ videos; transcripts
   noisy but voluminous.
2. **Twitter archive via twscrape or X API** — short-form only, lower
   per-row signal but high volume.
3. **YC `/library/` filtered to Tan interviews** — small set but high
   quality. Blocked on YC library being React-only.

In the meantime, `src/ai_intel/personas/garry_tan.md` is hand-distilled
from public Tan material (founder ↔ market fit, distribution > tech,
talk to 20 users before building). The evaluator already uses that file
directly; missing the corpus doesn't break anything.

Run:
    python -m scripts.ingest_tan
"""
from __future__ import annotations

import logging

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_tan.py is deferred — see top of file.\n"
        "  TL;DR: Tan has no public text blog. Content lives on YouTube\n"
        "  + Twitter. Would need yt-dlp transcripts or twscrape to\n"
        "  ingest. garry_tan persona at\n"
        "  src/ai_intel/personas/garry_tan.md is functional meanwhile."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
