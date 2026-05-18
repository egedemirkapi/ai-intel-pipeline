"""Ingest founder failure interviews from failory.com.

STATUS: stub.

Source: https://www.failory.com/interviews — each interview follows a
structured Q&A ("Why did your startup fail?", "What was your biggest
mistake?", etc.) which makes it an excellent failure corpus.

Implementation:
1. Index page: /interviews lists all interviews (paginated).
2. Each interview is a separate page.
3. Parse the Q&A blocks; concatenate as body.
4. build_item(source="failure_corpus", author=founder_name,
   entities_json={"kind": "post_mortem", "company": company_name,
   "cause": short_failure_label})

The "cause" field is what the evaluator agent uses for anti-pattern
matching. Initial labels: premature_scaling, no_pmf, wrong_team,
cash_crunch, regulatory, founder_conflict.

Run (today):
    python -m scripts.ingest_failory
"""
from __future__ import annotations

import logging
import sys

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_failory.py is a stub.\n"
        "  Source: https://www.failory.com/interviews\n"
        "  Each interview has a structured Q&A — parse blocks, build_item\n"
        "  source=failure_corpus + entities.cause for evaluator matching."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
