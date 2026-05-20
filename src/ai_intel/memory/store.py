"""Write side of the memory layer.

- ``embed_pending(engine, embedder, batch_size)`` walks the Item table
  and produces an Embedding row for every Item missing one. Idempotent.
- ``add_note(engine, text, embedder)`` records a user-typed memory and
  immediately embeds it.
- ``embed_text(embedder, text)`` exposes the raw embedder for callers
  that need a vector without persistence (used by retrieve.py).

Embedding key per item: ``title + " | " + (body or "")`` — sufficient
because items in this pipeline are short news items, not long documents.
For Item rows lacking body, title-only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
from sqlmodel import Session, select

from ai_intel.db.models import Embedding, Item, PersonalNote
from ai_intel.memory.embed import Embedder, get_embedder

logger = logging.getLogger(__name__)


def _item_text(item: Item) -> str:
    body = (item.body or "").strip()
    if body:
        return f"{item.title}\n\n{body}"
    return item.title


def embed_text(embedder: Embedder, text: str) -> np.ndarray:
    """Single-text convenience. Returns shape (dim,) float32."""
    return embedder.embed([text])[0]


def embed_pending(
    engine,
    embedder: Embedder | None = None,
    batch_size: int = 32,
    *,
    source: str | None = None,
) -> int:
    """Embed any Item that doesn't already have an Embedding of this model.

    Args:
        source: if given, only embed Items where Item.source == this value.
                Lets you bound expensive provider calls (e.g. Voyage free
                tier) to a sub-corpus like ``founder_brain``.

    Returns count of new Embedding rows.

    If any batches fail (provider rate-limit, network blip, etc.), the
    failed-item count is logged as a WARNING. Use ``embed_pending_detailed``
    if the caller needs structured (success, failure_count) numbers.
    """
    inserted, failed = embed_pending_detailed(
        engine, embedder=embedder, batch_size=batch_size, source=source,
    )
    return inserted


def embed_pending_detailed(
    engine,
    embedder: Embedder | None = None,
    batch_size: int = 32,
    *,
    source: str | None = None,
) -> tuple[int, int]:
    """Like ``embed_pending`` but returns ``(inserted, failed_item_count)``.

    Surfacing the failure count lets the CLI (``scripts/embed_now``) warn
    the user when the corpus is partially indexed — silently swallowing
    failures was the prior behavior and led to invisible bifurcation
    between embedded vs not-yet-embedded items.
    """
    embedder = embedder or get_embedder()
    inserted = 0
    failed = 0
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        existing_ids = set(session.exec(
            select(Embedding.item_id).where(
                Embedding.model == embedder.model,
                Embedding.item_id.is_not(None),  # noqa: E711
            )
        ).all())

        q = select(Item).where(Item.id.is_not(None))  # noqa: E711
        if source is not None:
            q = q.where(Item.source == source)
        unembedded: list[Item] = list(session.exec(q).all())
        unembedded = [it for it in unembedded if it.id not in existing_ids]

    if not unembedded:
        return 0, 0

    for i in range(0, len(unembedded), batch_size):
        batch = unembedded[i : i + batch_size]
        texts = [_item_text(it) for it in batch]
        try:
            vecs = embedder.embed(texts)
        except Exception as exc:
            logger.error(
                "Embed batch failed (%d items skipped): %s", len(batch), exc,
            )
            failed += len(batch)
            continue

        with Session(engine) as session:
            for it, vec in zip(batch, vecs):
                row = Embedding(
                    item_id=it.id,
                    note_id=None,
                    model=embedder.model,
                    dim=int(vec.shape[0]),
                    vector=vec.astype(np.float32).tobytes(),
                    created_at=now,
                )
                session.add(row)
                inserted += 1
            session.commit()

    if failed:
        logger.warning(
            "Embedded %d items with %s; %d items FAILED — corpus is partial. "
            "Re-run to retry.",
            inserted, embedder.model, failed,
        )
    else:
        logger.info("Embedded %d items with %s", inserted, embedder.model)
    return inserted, failed


def add_note(
    engine,
    text: str,
    *,
    source: str = "user_note",
    embedder: Embedder | None = None,
) -> int:
    """Persist a user note and embed it. Returns the new PersonalNote id."""
    text = (text or "").strip()
    if not text:
        raise ValueError("note text cannot be empty")
    embedder = embedder or get_embedder()
    now = datetime.now(timezone.utc)
    vec = embed_text(embedder, text)

    with Session(engine) as session:
        note = PersonalNote(text=text, source=source, created_at=now)
        session.add(note)
        session.commit()
        session.refresh(note)
        emb = Embedding(
            item_id=None,
            note_id=note.id,
            model=embedder.model,
            dim=int(vec.shape[0]),
            vector=vec.astype(np.float32).tobytes(),
            created_at=now,
        )
        session.add(emb)
        session.commit()
        return note.id  # type: ignore[return-value]
