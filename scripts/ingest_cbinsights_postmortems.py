"""Ingest CB Insights' public startup post-mortems list.

STATUS: stub. CB Insights paywalls most of their content — only a few
public pages are scrape-friendly.

Public sources that DO work:
1. https://www.cbinsights.com/research/startup-failure-post-mortem/  —
   their public "Top 20 reasons startups fail" page. Static HTML, no
   paywall. Each reason is a section with examples linked out.
2. https://www.cbinsights.com/research/startup-failure-reasons-top/  —
   alternative URL with similar content.

The 20 categories are themselves the most useful artifact for the
evaluator agent — they form a taxonomy of failure modes. Ingest them
as 20 small Items with:
- source="failure_corpus"
- entities_json={"kind": "failure_taxonomy", "category": <slug>}
- body = the section text + example companies they cite

Use this as a checklist the evaluator runs through for each candidate.

Run (today):
    python -m scripts.ingest_cbinsights_postmortems
"""
from __future__ import annotations

import logging
import sys

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_cbinsights_postmortems.py is a stub.\n"
        "  Source: cbinsights.com/research/startup-failure-post-mortem (public).\n"
        "  Parse the 20 failure categories as separate Items — they form\n"
        "  the evaluator's failure-mode checklist."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
