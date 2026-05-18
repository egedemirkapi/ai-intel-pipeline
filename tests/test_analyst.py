import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session

from ai_intel.analyst.digest import generate_digest
from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db


def insert_item(session, item_id, title, pub_dt, ai_rel=0.9, pre_score=8, classification="launch"):
    session.add(Item(
        id=item_id,
        source="hn",
        url=f"https://example.com/{item_id}",
        url_hash=f"h{item_id}",
        title=title,
        published_at=pub_dt,
        collected_at=datetime.now(timezone.utc),
        ai_relevance=ai_rel,
        pre_score=pre_score,
        classification=classification,
        entities_json="{}",
    ))


@pytest.mark.asyncio
async def test_digest_strips_hallucinated_ids(tmp_path: Path, monkeypatch):
    """Opus tries to include item_id 999 that doesn't exist in DB — must be stripped."""
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        insert_item(s, 1, "Real item", now - timedelta(minutes=30))
        insert_item(s, 2, "Real item 2", now - timedelta(minutes=60))
        for i in range(3, 13):
            insert_item(s, i, f"Item {i}", now - timedelta(minutes=10 * i))
        s.commit()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps({
        "summary": "Test summary",
        "top_50": [
            {"item_id": 1, "rank": 1, "why_it_matters": "Important"},
            {"item_id": 999, "rank": 2, "why_it_matters": "Fake"},
        ],
    }))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    monkeypatch.setattr("ai_intel.analyst.digest.get_anthropic_client", lambda: fake_client)
    monkeypatch.setattr("ai_intel.analyst.digest.PROMPT_PATH", tmp_path / "p.txt")
    (tmp_path / "p.txt").write_text("prompt")

    digest = await generate_digest(
        engine, window_start=now - timedelta(hours=2), window_end=now, model="opus"
    )
    selected_ids = [s["item_id"] for s in digest["top_items"]]
    assert 1 in selected_ids
    assert 999 not in selected_ids


@pytest.mark.asyncio
async def test_digest_enforces_window(tmp_path: Path, monkeypatch):
    """Opus tries to smuggle in item_id 2 which is OUTSIDE the 2h window — must be stripped."""
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        insert_item(s, 1, "In window", now - timedelta(minutes=30))
        insert_item(s, 2, "OUT of window", now - timedelta(hours=5))
        for i in range(3, 13):
            insert_item(s, i, f"Item {i}", now - timedelta(minutes=10 * i))
        s.commit()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps({
        "summary": "S",
        "top_50": [
            {"item_id": 1, "rank": 1, "why_it_matters": "a"},
            {"item_id": 2, "rank": 2, "why_it_matters": "b"},
        ],
    }))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    monkeypatch.setattr("ai_intel.analyst.digest.get_anthropic_client", lambda: fake_client)
    monkeypatch.setattr("ai_intel.analyst.digest.PROMPT_PATH", tmp_path / "p.txt")
    (tmp_path / "p.txt").write_text("prompt")

    digest = await generate_digest(
        engine, window_start=now - timedelta(hours=2), window_end=now, model="opus"
    )
    selected_ids = [s["item_id"] for s in digest["top_items"]]
    assert 1 in selected_ids
    assert 2 not in selected_ids


@pytest.mark.asyncio
async def test_digest_runs_analyst_even_on_small_windows(tmp_path: Path, monkeypatch):
    """Small batches (<10 items) should still get analyst 'why it matters' — Haiku
    is cheap and a 3-item digest with analysis beats a headline-only fallback."""
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        for i in range(1, 4):
            insert_item(s, i, f"Item {i}", now - timedelta(minutes=20 * i), pre_score=10 - i)
        s.commit()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps({
        "summary": "Three things happened.",
        "top_50": [
            {"item_id": 1, "rank": 1, "why_it_matters": "a"},
            {"item_id": 2, "rank": 2, "why_it_matters": "b"},
            {"item_id": 3, "rank": 3, "why_it_matters": "c"},
        ],
    }))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    monkeypatch.setattr("ai_intel.analyst.digest.get_anthropic_client", lambda: fake_client)
    monkeypatch.setattr("ai_intel.analyst.digest.PROMPT_PATH", tmp_path / "p.txt")
    (tmp_path / "p.txt").write_text("prompt")

    digest = await generate_digest(
        engine, window_start=now - timedelta(hours=2), window_end=now, model="haiku"
    )
    assert len(digest["top_items"]) == 3
    assert digest["summary"] == "Three things happened."
    fake_client.messages.create.assert_called_once()
