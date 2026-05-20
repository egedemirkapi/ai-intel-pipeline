"""One-shot: enrich every Item that doesn't have classification yet.

Same effect as the enrichment step inside ``python -m ai_intel --once``,
but WITHOUT firing the collectors or sending a digest email. Useful
right after a bulk backfill (e.g. ``scripts/backfill_hn_history.py``)
when you want to populate entities_json + ai_relevance for the new
rows without triggering the full pipeline.

Run:
    python scripts/enrich_pending.py
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from ai_intel.db.session import get_engine, init_db  # noqa: E402
from ai_intel.enrichment.runner import enrich_new_items  # noqa: E402
from ai_intel.logging_config import setup_logging  # noqa: E402
from ai_intel.scheduler import load_config  # noqa: E402

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Enrich any unclassified Items")
    parser.add_argument("--db", default="data/items.db")
    parser.add_argument("--model", default=None,
                        help="Override the enrichment model")
    args = parser.parse_args(argv)

    config = load_config()
    model = args.model or config["llm"]["enrichment_model"]

    engine = get_engine(Path(args.db))
    init_db(engine)

    n = asyncio.run(enrich_new_items(engine, model=model))
    print(f"Enriched {n} items with {model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
