import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from ai_intel.db.models import Item
from ai_intel.enrichment.enrich import enrich_batch


def make_item(title: str, item_id: int) -> Item:
    return Item(
        id=item_id,
        source="hn",
        url=f"https://example.com/{item_id}",
        url_hash=f"hash{item_id}",
        title=title,
        published_at=datetime.now(timezone.utc),
        collected_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_enrich_batch_parses_json():
    items = [make_item("Anthropic launches Claude 5", 1), make_item("Random hire", 2)]
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=json.dumps([
        {"item_id": 1, "classification": "launch", "ai_relevance": 0.95,
         "entities": {"companies": ["Anthropic"]}, "pre_score": 9, "skip_reason": None},
        {"item_id": 2, "classification": "hire", "ai_relevance": 0.1,
         "entities": {}, "pre_score": 2, "skip_reason": "not AI relevant"},
    ]))]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    enriched = await enrich_batch(items, client=fake_client, model="claude-haiku-4-5-20251001")
    assert enriched[1]["classification"] == "launch"
    assert enriched[1]["ai_relevance"] == 0.95
    assert enriched[2]["skip_reason"] == "not AI relevant"


@pytest.mark.asyncio
async def test_enrich_batch_handles_empty():
    enriched = await enrich_batch([], client=MagicMock(), model="m")
    assert enriched == {}


@pytest.mark.asyncio
async def test_enrich_batch_returns_empty_on_malformed_json():
    items = [make_item("X", 1)]
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text="not json at all")]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    enriched = await enrich_batch(items, client=fake_client, model="m")
    assert enriched == {}


@pytest.mark.asyncio
async def test_enrich_batch_extracts_json_from_prose():
    """Regression: Haiku sometimes wraps JSON in explanatory prose despite the
    'no prose' instruction. The extractor must dig the JSON out of the surrounding text."""
    items = [make_item("Anthropic ships X", 1)]
    inner_json = json.dumps([
        {"item_id": 1, "classification": "launch", "ai_relevance": 0.9,
         "entities": {}, "pre_score": 8, "skip_reason": None},
    ])
    wrapped = (
        "Sure, here is the analysis of the items you provided:\n\n"
        f"{inner_json}\n\n"
        "Let me know if you'd like further refinements."
    )
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=wrapped)]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    enriched = await enrich_batch(items, client=fake_client, model="m")
    assert enriched[1]["classification"] == "launch"


@pytest.mark.asyncio
async def test_enrich_batch_strips_markdown_fences():
    """Regression: Haiku sometimes wraps JSON in ```json ... ``` fences."""
    items = [make_item("Anthropic ships X", 1)]
    inner_json = json.dumps([
        {"item_id": 1, "classification": "launch", "ai_relevance": 0.9,
         "entities": {}, "pre_score": 8, "skip_reason": None},
    ])
    fenced = f"```json\n{inner_json}\n```"
    fake_response = MagicMock()
    fake_response.content = [MagicMock(text=fenced)]
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    enriched = await enrich_batch(items, client=fake_client, model="m")
    assert enriched[1]["classification"] == "launch"
    assert enriched[1]["ai_relevance"] == 0.9
