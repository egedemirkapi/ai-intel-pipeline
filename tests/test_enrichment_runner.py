import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session

from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db
from ai_intel.enrichment.runner import enrich_new_items


@pytest.mark.asyncio
async def test_enrich_runner_writes_back(tmp_path: Path, monkeypatch):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    with Session(engine) as s:
        s.add(Item(
            id=1, source="hn", url="https://example.com/1", url_hash="h1",
            title="OpenAI ships new GPT",
            published_at=datetime.now(timezone.utc),
            collected_at=datetime.now(timezone.utc),
        ))
        s.commit()

    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps([
        {"item_id": 1, "classification": "launch", "ai_relevance": 0.95,
         "entities": {"companies": ["OpenAI"]}, "pre_score": 9, "skip_reason": None},
    ]))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    monkeypatch.setattr("ai_intel.enrichment.runner.get_anthropic_client", lambda: fake_client)
    monkeypatch.setattr("ai_intel.enrichment.enrich.PROMPT_PATH", tmp_path / "prompt.txt")
    (tmp_path / "prompt.txt").write_text("dummy prompt")

    enriched = await enrich_new_items(engine, model="claude-haiku-4-5-20251001", batch_size=10)
    assert enriched == 1

    with Session(engine) as s:
        item = s.get(Item, 1)
        assert item.classification == "launch"
        assert item.ai_relevance == 0.95
        assert item.pre_score == 9
        assert "OpenAI" in (item.entities_json or "")


@pytest.mark.asyncio
async def test_enrich_runner_no_items(tmp_path: Path, monkeypatch):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    fake_client = MagicMock()
    monkeypatch.setattr("ai_intel.enrichment.runner.get_anthropic_client", lambda: fake_client)
    enriched = await enrich_new_items(engine, model="m", batch_size=10)
    assert enriched == 0
    fake_client.messages.create.assert_not_called()
