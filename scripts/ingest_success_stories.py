"""Ingest the success_corpus case-study markdowns into items.db.

Source: ``config/success_stories/*.md`` — one markdown per company,
each a structured ~400-word case study with sections:

    # <Company> — <tagline>
    ## Founding insight
    ## Initial wedge
    ## Timing call
    ## Distribution mechanism
    ## 10× moment
    ## Default-status moat

This is the "how winners thought" half of the founder corpus, the
counterpart to ``failure_corpus`` (Failory cemetery) and
``founder_brain`` (PG / Altman / a16z essays). Stored as Item rows
with ``source='success_corpus'`` so the existing recall pipeline
(proposer's ``_recall_success_patterns``) can retrieve them by
semantic similarity.

Run:
    python -m scripts.ingest_success_stories
    python -m scripts.ingest_success_stories --db data/items.db --corpus-dir config/success_stories

Idempotent on URL — re-runs only insert newly-added markdown files.
After ingest, embed with::

    python -m scripts.embed_now --db data/items.db --source success_corpus
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Iterator

from ai_intel.db.session import get_engine, init_db
from ai_intel.logging_config import setup_logging
from scripts._common import build_item, clean_whitespace, ingest_batch

logger = logging.getLogger(__name__)

DEFAULT_CORPUS_DIR = Path("config/success_stories")
SOURCE = "success_corpus"
CLASSIFICATION = "case_study"
KIND = "case_study"


def _title_from_markdown(text: str, fallback: str) -> str:
    """Extract the first H1 from a markdown file; fall back to ``fallback``."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _author_from_slug(slug: str) -> str:
    """Slug -> human company name. ``hugging-face`` -> ``Hugging Face``."""
    return slug.replace("-", " ").replace("_", " ").title()


def iter_case_studies(corpus_dir: Path) -> Iterator:
    """Yield one Item per markdown file in ``corpus_dir``."""
    md_files = sorted(corpus_dir.glob("*.md"))
    if not md_files:
        logger.warning("no markdown files found in %s", corpus_dir)
        return
    for md_path in md_files:
        slug = md_path.stem
        try:
            raw = md_path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read %s: %s", md_path, exc)
            continue
        body = clean_whitespace(raw)
        if len(body) < 200:
            logger.warning("body too short for %s — skipping", md_path)
            continue
        title = _title_from_markdown(raw, fallback=_author_from_slug(slug))
        author = _author_from_slug(slug)
        # Synthetic URL — stable + unique per case study, used by
        # insert_if_new() for idempotency on re-runs.
        url = f"local://success_corpus/{slug}"
        yield build_item(
            url=url,
            title=title,
            body=body,
            author=author,
            kind=KIND,
            source=SOURCE,
            classification=CLASSIFICATION,
            extra_entities={"company": slug, "outcome": "scaled"},
        )


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Ingest config/success_stories/*.md into success_corpus",
    )
    parser.add_argument("--db", default="data/items.db", help="Path to items.db")
    parser.add_argument(
        "--corpus-dir",
        default=str(DEFAULT_CORPUS_DIR),
        help="Directory of *.md case-study files",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    corpus_dir = Path(args.corpus_dir)
    if not corpus_dir.exists():
        logger.error("corpus dir not found: %s", corpus_dir)
        return 1

    engine = get_engine(db_path)
    init_db(engine)

    logger.info("Reading case studies from %s", corpus_dir)
    inserted, skipped = ingest_batch(
        engine,
        iter_case_studies(corpus_dir),
        label="success_corpus",
    )
    logger.info("Done. inserted=%d skipped=%d", inserted, skipped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
