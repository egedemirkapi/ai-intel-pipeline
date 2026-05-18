from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: str = Field(index=True)
    url: str = Field(unique=True)
    url_hash: str = Field(unique=True, index=True)
    title: str
    body: Optional[str] = None
    author: Optional[str] = None
    published_at: datetime = Field(index=True)
    collected_at: datetime
    classification: Optional[str] = None
    entities_json: Optional[str] = None  # JSON-encoded dict
    pre_score: Optional[int] = None
    ai_relevance: Optional[float] = None
    skip_reason: Optional[str] = None
    sent_in_digest_at: Optional[datetime] = Field(default=None, index=True)
    raw_json: Optional[str] = None


class Digest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    window_start: datetime
    window_end: datetime
    items_considered: int
    items_selected: int
    summary: Optional[str] = None
    pdf_path: Optional[str] = None
    sent_at: Optional[datetime] = None
    sent_to: Optional[str] = None


# ─── Jarvis memory layer (Phase 1) ──────────────────────────────────────
#
# Embeddings live in a separate table so re-running with a different
# embedding model is just a re-fill (no schema change). Vector stored as
# packed float32 bytes for compactness.


class Embedding(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # Exactly one of these two is set; the pair (item_id, note_id) is the
    # natural key for "what does this embedding cover".
    item_id: Optional[int] = Field(default=None, foreign_key="item.id", index=True)
    note_id: Optional[int] = Field(default=None, foreign_key="personalnote.id", index=True)
    model: str  # e.g. "voyage-3" or "fake-256"
    dim: int
    vector: bytes  # np.float32(dim,).tobytes()
    created_at: datetime = Field(index=True)


class PersonalNote(SQLModel, table=True):
    """User-typed memories (`jarvis note "..."`).

    Source-tagged so retrieval can filter notes vs. intel-feed items.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str
    source: str = Field(default="user_note", index=True)
    created_at: datetime = Field(index=True)


class MemoryQuery(SQLModel, table=True):
    """Append-only audit log of recall queries — useful for debugging
    retrieval quality and for the BrainBench-style replay loop later.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    query: str
    k: int
    result_ids_json: Optional[str] = None  # JSON list[int] of Item/Note ids returned
    created_at: datetime = Field(index=True)
