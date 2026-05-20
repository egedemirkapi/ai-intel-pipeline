"""Ingest YC Library articles into the founder_brain corpus.

STATUS: deferred — non-trivial (probed 2026-05-19).

Source: https://www.ycombinator.com/library/ (~460 articles enumerated
via /library/sitemap.xml). High-value content: founder interviews,
how-to essays, Startup School material.

Why deferred:
The library is React-rendered. Fetching a /library/<slug> page returns
~67KB of HTML, but `<h1>` is absent and the largest `<div>` has empty
text content — the article body is injected by JavaScript at runtime.
Static HTML parsing (the pattern every other ingester uses) yields
nothing.

Three realistic paths forward when prioritizing this:
1. **Playwright/headless browser** — render the page, then extract.
   Adds Chromium (~300MB) and ~3s/article render time (~25min total
   for 460). Playwright is already in `pyproject.toml` for the PDF
   generator, so the dep cost is paid; only render time is new.
2. **Find the JSON API** — the React app calls something like
   `/api/library/<id>`; inspect network in DevTools to discover it.
   If available, fastest path.
3. **WordPress mirror** — https://blog.ycombinator.com serves some of
   the same content via standard sitemap-able WordPress. Subset only,
   but might cover the highest-quality essays.

In the meantime, `src/ai_intel/personas/yc_partner.md` is hand-distilled
from public YC material and feeds the evaluator directly. Missing the
corpus doesn't break the system, only limits what
`recall(... source='founder_brain')` surfaces for YC-flavored queries.

Run:
    python -m scripts.ingest_yc
"""
from __future__ import annotations

import logging

from ai_intel.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    logger.warning(
        "ingest_yc.py is deferred — see top of file.\n"
        "  TL;DR: YC library is React-rendered; static HTML parsing\n"
        "  finds no body. Needs Playwright or JSON API to do properly.\n"
        "  ~460 articles available. yc_partner persona at\n"
        "  src/ai_intel/personas/yc_partner.md is functional meanwhile."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
