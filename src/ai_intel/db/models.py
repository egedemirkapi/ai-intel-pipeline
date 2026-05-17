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
