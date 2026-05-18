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


# ─── Agent fleet (Phase 7) ──────────────────────────────────────────────
#
# Every @agent run gets a row in AgentRun. Status transitions:
#   pending → running → completed | failed
# Tokens + cost are recorded so `jarvis agents status` and `jarvis cost`
# can answer "what did the fleet cost this week" cheaply.


class AgentRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: str = Field(index=True)
    status: str = Field(index=True)  # pending | running | completed | failed
    started_at: datetime = Field(index=True)
    finished_at: Optional[datetime] = Field(default=None, index=True)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    cost_estimate_usd: float = Field(default=0.0)
    auth_mode: Optional[str] = None  # "oauth" | "api_key" | None (no LLM call)
    summary: Optional[str] = None
    error: Optional[str] = None
    output_pointer_json: Optional[str] = None  # FK-ish hint to per-agent output table


# Phase 8 output tables — created now so the schema is stable; Phase 8
# agents populate them.


class SaturationAssessment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic: str = Field(index=True)
    score: float  # [0, 1] — 1 = saturated
    sources_json: Optional[str] = None  # supporting Item ids + URLs
    competitor_count: int = Field(default=0)
    assessed_at: datetime = Field(index=True)
    expires_at: datetime = Field(index=True)  # cache TTL, default +7 days
    notes: Optional[str] = None


class PainCluster(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    label: str = Field(index=True)
    examples_json: Optional[str] = None
    member_item_ids_json: Optional[str] = None
    last_updated: datetime = Field(index=True)


class IdeaCandidate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    proposed_at: datetime = Field(index=True)
    idea_text: str
    tech_basis: Optional[str] = None
    pain_basis_cluster_id: Optional[int] = Field(default=None, foreign_key="paincluster.id")
    evaluator_score: Optional[int] = None  # 0-100
    evaluator_verdict: Optional[str] = None  # "killed" | "needs_work" | "escalated"
    persona_critiques_json: Optional[str] = None  # {pid: {score, comment}, ...}
    failure_parallels_json: Optional[str] = None  # cite ≥2 from failure_corpus
    status: str = Field(default="proposed", index=True)
    # proposed | killed | needs_work | escalated | shown
