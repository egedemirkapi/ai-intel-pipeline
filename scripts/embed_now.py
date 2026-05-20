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

from dotenv import load_dotenv

# Load .env BEFORE importing the memory layer so JARVIS_EMBEDDING_PROVIDER
# and VOYAGE_API_KEY take effect when get_embedder() runs. Without this,
# the embedder silently falls back to FakeEmbedder and the resulting
# fake-256 rows don't match queries made under the voyage-3 model.
load_dotenv()

from ai_intel.db.session import get_engine, init_db  # noqa: E402
from ai_intel.logging_config import setup_logging  # noqa: E402
from ai_intel.memory.store import embed_pending_detailed  # noqa: E402


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
    inserted, failed = embed_pending_detailed(engine, source=args.source)
    src_suffix = f" (source={args.source})" if args.source else ""
    print(f"embedded {inserted} new rows{src_suffix}")
    if failed:
        # Non-zero exit so callers (cron, scripts) can detect partial runs.
        print(
            f"WARNING: {failed} items FAILED to embed — corpus is partial. "
            f"Re-run `python -m scripts.embed_now{src_suffix.replace(' (','').replace(')','').replace('source=', ' --source ')}` to retry."
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
