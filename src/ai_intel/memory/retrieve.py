"""Read side of the memory layer — semantic top-k recall.

Cosine similarity done in numpy. For ~100k items × 1024-dim, this is
~400MB of vectors held in RAM during a query and a single dot product
that completes in <100ms. If we ever cross 1M items we'd move to
sqlite-vec or LanceDB; that's not the current bottleneck.

Returns ``RecallResult`` objects so callers can render hits without
re-hitting the DB.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

import numpy as np
from sqlmodel import Session, select

from ai_intel.db.models import Embedding, Item, MemoryQuery, PersonalNote
from ai_intel.memory.embed import Embedder, get_embedder

logger = logging.getLogger(__name__)

HitType = Literal["item", "note"]


@dataclass
class RecallResult:
    hit_type: HitType
    id: int                # Item.id or PersonalNote.id
    score: float           # cosine similarity, [-1, 1]
    title: str
    snippet: str
    source: str
    url: Optional[str]     # None for notes
    published_at: Optional[datetime]
    entities: dict         # parsed from Item.entities_json, {} for notes


def _decode(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32).reshape(dim)


def recall(
    engine,
    query: str,
    *,
    k: int = 10,
    source: str | None = None,
    entity: str | None = None,
    hit_types: tuple[HitType, ...] = ("item", "note"),
    embedder: Embedder | None = None,
    log_query: bool = True,
) -> list[RecallResult]:
    """Top-k semantic recall.

    Filters:
      - source: restrict to Item.source / PersonalNote.source == this value
      - entity: case-insensitive substring match in Item.entities_json
                (notes have no entities, so this implicitly drops them)
      - hit_types: which kinds of rows to consider
    """
    query = (query or "").strip()
    if not query:
        return []

    embedder = embedder or get_embedder()
    q_vec = embedder.embed([query])[0]
    # Normalize — embedders return normalized but defensive copy is cheap
    q_norm = np.linalg.norm(q_vec)
    if q_norm > 0:
        q_vec = q_vec / q_norm

    with Session(engine) as session:
        rows = session.exec(
            select(Embedding).where(Embedding.model == embedder.model)
        ).all()

        if not rows:
            if log_query:
                _log_query(session, query, k, [])
            return []

        # Stack into a single matrix for one dot product
        mat = np.stack([_decode(r.vector, r.dim) for r in rows])
        sims = mat @ q_vec  # (N,)

        order = np.argsort(-sims)  # descending

        results: list[RecallResult] = []
        for idx in order:
            r = rows[int(idx)]
            score = float(sims[int(idx)])
            if r.item_id is not None and "item" in hit_types:
                item = session.get(Item, r.item_id)
                if item is None:
                    continue
                if source and item.source != source:
                    continue
                entities = {}
                if item.entities_json:
                    try:
                        entities = json.loads(item.entities_json)
                    except json.JSONDecodeError:
                        entities = {}
                if entity and not _entity_match(entities, entity):
                    continue
                results.append(RecallResult(
                    hit_type="item",
                    id=item.id,  # type: ignore[arg-type]
                    score=score,
                    title=item.title,
                    snippet=(item.body or "")[:240],
                    source=item.source,
                    url=item.url,
                    published_at=item.published_at,
                    entities=entities,
                ))
            elif r.note_id is not None and "note" in hit_types:
                if entity:
                    continue  # notes have no entity index
                note = session.get(PersonalNote, r.note_id)
                if note is None:
                    continue
                if source and note.source != source:
                    continue
                results.append(RecallResult(
                    hit_type="note",
                    id=note.id,  # type: ignore[arg-type]
                    score=score,
                    title=note.text[:80],
                    snippet=note.text[:240],
                    source=note.source,
                    url=None,
                    published_at=note.created_at,
                    entities={},
                ))
            if len(results) >= k:
                break

        if log_query:
            _log_query(session, query, k, results)

        return results


def _entity_match(entities: dict, needle: str) -> bool:
    needle_lc = needle.lower()
    # entities_json shape varies; flatten and substring-match
    def walk(v):
        if isinstance(v, str):
            return needle_lc in v.lower()
        if isinstance(v, list):
            return any(walk(x) for x in v)
        if isinstance(v, dict):
            return any(walk(x) for x in v.values())
        return False
    return walk(entities)


def _log_query(
    session: Session,
    query: str,
    k: int,
    results: list[RecallResult],
) -> None:
    try:
        ids_payload = [
            {"hit_type": r.hit_type, "id": r.id, "score": round(r.score, 4)}
            for r in results
        ]
        row = MemoryQuery(
            query=query[:512],
            k=k,
            result_ids_json=json.dumps(ids_payload),
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.commit()
    except Exception as exc:
        logger.debug("MemoryQuery log failed (non-fatal): %s", exc)
