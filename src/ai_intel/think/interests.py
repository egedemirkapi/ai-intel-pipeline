"""User interests — the seeds for the briefing's suggestion section.

An interest is just a ``PersonalNote`` tagged ``source="interest"``.
Storing it as a note means it is embedded like everything else, so the
briefing can semantic-recall the intel items that match it.
"""
from __future__ import annotations

from sqlmodel import Session, desc, select

from ai_intel.db.models import Embedding, PersonalNote
from ai_intel.memory.store import add_note

INTEREST_SOURCE = "interest"


def add_interest(engine, text: str, *, embedder=None) -> int:
    """Add an interest. Returns the new PersonalNote id."""
    return add_note(engine, text, source=INTEREST_SOURCE, embedder=embedder)


def list_interests(engine) -> list[dict]:
    """Return ``[{id, text, created_at}]``, newest first."""
    with Session(engine) as s:
        rows = list(s.exec(
            select(PersonalNote)
            .where(PersonalNote.source == INTEREST_SOURCE)
            .order_by(desc(PersonalNote.created_at))
        ))
    return [
        {
            "id": r.id,
            "text": r.text,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


def delete_interest(engine, note_id: int) -> bool:
    """Delete an interest and its embedding. Returns False if not found."""
    with Session(engine) as s:
        note = s.get(PersonalNote, note_id)
        if note is None or note.source != INTEREST_SOURCE:
            return False
        for emb in s.exec(
            select(Embedding).where(Embedding.note_id == note_id)
        ).all():
            s.delete(emb)
        s.delete(note)
        s.commit()
    return True
