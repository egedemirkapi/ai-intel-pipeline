"""One-shot: embed every Item that doesn't have an Embedding yet.

    python -m scripts.embed_now [--db data/items.db]

Useful after running ingest_pg / ingest_altman by hand, since those
scripts only insert Items — the existing pipeline embeds them later
via the scheduler, but if you're not running the scheduler, you need
this.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from ai_intel.db.session import get_engine, init_db
from ai_intel.logging_config import setup_logging
from ai_intel.memory.store import embed_pending


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Embed all pending Items")
    parser.add_argument("--db", default="data/items.db")
    parser.add_argument(
        "--source",
        default=None,
        help="Only embed Items where Item.source == this value. "
             "Useful when on Voyage free tier — pass 'founder_brain' to "
             "bound the work.",
    )
    args = parser.parse_args(argv)

    engine = get_engine(Path(args.db))
    init_db(engine)
    n = embed_pending(engine, source=args.source)
    print(f"embedded {n} new rows" + (f" (source={args.source})" if args.source else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
