from datetime import datetime, timezone, timedelta

import pytest
from pytest_httpx import HTTPXMock

from ai_intel.collectors.product_hunt import ProductHuntCollector

PH_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"


@pytest.mark.asyncio
async def test_ph_returns_item(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setenv("PRODUCT_HUNT_TOKEN", "fake-token-123")

    httpx_mock.add_response(
        url=PH_GRAPHQL_URL,
        json={
            "data": {
                "posts": {
                    "edges": [
                        {
                            "node": {
                                "id": "42",
                                "name": "AI Notes",
                                "tagline": "AI-powered note taker",
                                "url": "https://producthunt.com/posts/ai-notes",
                                "createdAt": "2026-05-17T10:00:00Z",
                                "user": {"name": "Alice"},
                            }
                        }
                    ]
                }
            }
        },
    )

    c = ProductHuntCollector()
    items = await c.fetch_since(datetime.now(timezone.utc) - timedelta(hours=2))
    assert len(items) == 1
    assert items[0].title == "AI Notes — AI-powered note taker"


@pytest.mark.asyncio
async def test_ph_no_token_returns_empty(monkeypatch):
    monkeypatch.delenv("PRODUCT_HUNT_TOKEN", raising=False)
    c = ProductHuntCollector()
    items = await c.fetch_since(datetime.now(timezone.utc) - timedelta(hours=2))
    assert items == []
