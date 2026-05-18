"""Tests for the Jarvis memory layer (Phase 1)."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from sqlmodel import Session, SQLModel, create_engine

from ai_intel.db.models import Embedding, Item, MemoryQuery, PersonalNote
from ai_intel.memory.embed import FakeEmbedder, get_embedder
from ai_intel.memory.retrieve import recall
from ai_intel.memory.store import add_note, embed_pending, embed_text


@pytest.fixture
def engine():
    """In-memory SQLite with all tables created."""
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture
def embedder():
    return FakeEmbedder(dim=128, model="fake-128-test")


def _make_item(
    *,
    title: str,
    body: str = "",
    source: str = "hn",
    url: str | None = None,
    entities: dict | None = None,
) -> Item:
    import hashlib
    import json
    url = url or f"https://example.test/{hashlib.md5(title.encode()).hexdigest()[:10]}"
    return Item(
        source=source,
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest()[:32],
        title=title,
        body=body,
        published_at=datetime.now(timezone.utc),
        collected_at=datetime.now(timezone.utc),
        entities_json=json.dumps(entities) if entities else None,
    )


# ---------------------------------------------------------------------------
# Embedder behavior
# ---------------------------------------------------------------------------


def test_fake_embedder_is_deterministic():
    e = FakeEmbedder(dim=64)
    a = e.embed(["hello world"])[0]
    b = e.embed(["hello world"])[0]
    assert np.allclose(a, b)


def test_fake_embedder_l2_normalized():
    e = FakeEmbedder(dim=64)
    v = e.embed(["any text at all"])[0]
    assert np.isclose(np.linalg.norm(v), 1.0, atol=1e-5)


def test_fake_embedder_similar_text_correlates():
    """Lexically overlapping texts should have higher cosine than unrelated ones."""
    e = FakeEmbedder(dim=512)
    a, b, c = e.embed([
        "openai launches new gpt model",
        "openai releases new gpt model today",
        "the weather in paris is rainy",
    ])
    sim_ab = float(a @ b)
    sim_ac = float(a @ c)
    assert sim_ab > sim_ac, f"expected overlap to help: ab={sim_ab} vs ac={sim_ac}"


def test_get_embedder_defaults_to_fake(monkeypatch):
    monkeypatch.delenv("JARVIS_EMBEDDING_PROVIDER", raising=False)
    e = get_embedder()
    assert isinstance(e, FakeEmbedder)


def test_get_embedder_unknown_raises(monkeypatch):
    monkeypatch.setenv("JARVIS_EMBEDDING_PROVIDER", "bogus")
    with pytest.raises(ValueError):
        get_embedder()


def test_voyage_embedder_requires_key(monkeypatch):
    from ai_intel.memory.embed import VoyageEmbedder
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="VOYAGE_API_KEY"):
        VoyageEmbedder()


# ---------------------------------------------------------------------------
# Store: embed_pending
# ---------------------------------------------------------------------------


def test_embed_pending_creates_one_row_per_item(engine, embedder):
    with Session(engine) as s:
        s.add(_make_item(title="OpenAI launches GPT-X"))
        s.add(_make_item(title="Anthropic releases Claude Y"))
        s.commit()

    n = embed_pending(engine, embedder=embedder)
    assert n == 2

    with Session(engine) as s:
        rows = s.exec(  # type: ignore[attr-defined]
            __import__("sqlmodel").select(Embedding)
        ).all()
    assert len(rows) == 2
    assert all(r.model == "fake-128-test" for r in rows)
    assert all(r.dim == 128 for r in rows)
    # Vector blobs should decode to dim float32s
    for r in rows:
        v = np.frombuffer(r.vector, dtype=np.float32)
        assert v.shape == (128,)


def test_embed_pending_idempotent(engine, embedder):
    with Session(engine) as s:
        s.add(_make_item(title="OpenAI launches GPT-X"))
        s.commit()
    n1 = embed_pending(engine, embedder=embedder)
    n2 = embed_pending(engine, embedder=embedder)
    assert n1 == 1
    assert n2 == 0


def test_embed_pending_uses_title_and_body(engine, embedder):
    with Session(engine) as s:
        s.add(_make_item(title="t", body="this body content matters too"))
        s.commit()
    embed_pending(engine, embedder=embedder)
    # We expect title+body to be hashed (not just title). Verify by
    # comparing to title-only embedding.
    v_title_only = embed_text(embedder, "t")
    with Session(engine) as s:
        row = s.exec(__import__("sqlmodel").select(Embedding)).first()
    v_stored = np.frombuffer(row.vector, dtype=np.float32)
    # Should differ — body changed the vector
    assert not np.allclose(v_stored, v_title_only)


# ---------------------------------------------------------------------------
# Store: notes
# ---------------------------------------------------------------------------


def test_add_note_persists_and_embeds(engine, embedder):
    nid = add_note(engine, "remember to follow up on Stripe deal", embedder=embedder)
    assert nid > 0
    with Session(engine) as s:
        n = s.get(PersonalNote, nid)
        assert n is not None
        assert n.source == "user_note"
        embs = s.exec(__import__("sqlmodel").select(Embedding).where(
            Embedding.note_id == nid
        )).all()
        assert len(embs) == 1


def test_add_note_rejects_empty(engine, embedder):
    with pytest.raises(ValueError):
        add_note(engine, "   ", embedder=embedder)


# ---------------------------------------------------------------------------
# Retrieve
# ---------------------------------------------------------------------------


def test_recall_returns_top_k_ordered(engine, embedder):
    items = [
        _make_item(title="OpenAI launches GPT-X model", source="hn"),
        _make_item(title="Stripe announces atlas product", source="hn"),
        _make_item(title="Weather forecast for Paris", source="rss"),
        _make_item(title="OpenAI partners with Microsoft on GPT", source="rss"),
    ]
    with Session(engine) as s:
        for it in items:
            s.add(it)
        s.commit()
    embed_pending(engine, embedder=embedder)

    hits = recall(engine, "OpenAI GPT release", k=3, embedder=embedder)
    assert len(hits) == 3
    # Top hit should be about OpenAI
    assert "OpenAI" in hits[0].title or "GPT" in hits[0].title
    # Scores monotonically decreasing
    for a, b in zip(hits, hits[1:]):
        assert a.score >= b.score


def test_recall_source_filter(engine, embedder):
    items = [
        _make_item(title="OpenAI launches GPT-X", source="hn"),
        _make_item(title="OpenAI partners with Microsoft", source="rss"),
    ]
    with Session(engine) as s:
        for it in items:
            s.add(it)
        s.commit()
    embed_pending(engine, embedder=embedder)

    hn_only = recall(engine, "openai", k=10, source="hn", embedder=embedder)
    assert all(h.source == "hn" for h in hn_only)
    assert len(hn_only) == 1


def test_recall_entity_filter(engine, embedder):
    with Session(engine) as s:
        s.add(_make_item(title="A", entities={"orgs": ["OpenAI"]}))
        s.add(_make_item(title="B", entities={"orgs": ["Anthropic"]}))
        s.commit()
    embed_pending(engine, embedder=embedder)

    only_openai = recall(engine, "anything", k=10, entity="openai", embedder=embedder)
    assert len(only_openai) == 1
    assert only_openai[0].title == "A"


def test_recall_empty_query_returns_empty(engine, embedder):
    assert recall(engine, "", embedder=embedder) == []
    assert recall(engine, "   ", embedder=embedder) == []


def test_recall_logs_query(engine, embedder):
    with Session(engine) as s:
        s.add(_make_item(title="OpenAI launches GPT-X"))
        s.commit()
    embed_pending(engine, embedder=embedder)

    recall(engine, "openai", k=3, embedder=embedder)

    with Session(engine) as s:
        logs = s.exec(__import__("sqlmodel").select(MemoryQuery)).all()
    assert len(logs) == 1
    assert logs[0].query == "openai"
    assert logs[0].k == 3


def test_recall_includes_notes(engine, embedder):
    with Session(engine) as s:
        s.add(_make_item(title="OpenAI ships GPT-X"))
        s.commit()
    embed_pending(engine, embedder=embedder)
    add_note(engine, "i should buy openai stock if it goes public", embedder=embedder)

    hits = recall(engine, "openai stock", k=5, embedder=embedder)
    assert any(h.hit_type == "note" for h in hits)


def test_recall_can_exclude_notes(engine, embedder):
    add_note(engine, "buy openai stock", embedder=embedder)
    hits = recall(engine, "openai", k=5, embedder=embedder, hit_types=("item",))
    assert all(h.hit_type == "item" for h in hits)
