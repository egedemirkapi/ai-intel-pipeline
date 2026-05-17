from datetime import datetime, timezone, timedelta

import pytest
from pytest_httpx import HTTPXMock

from ai_intel.collectors.hn import HackerNewsCollector


@pytest.mark.asyncio
async def test_hn_filters_ai_titles(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/topstories.json",
        json=[1, 2, 3],
    )
    now_ts = int(datetime.now(timezone.utc).timestamp())
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/1.json",
        json={"id": 1, "title": "Anthropic launches Claude 5", "url": "https://x.com/1", "time": now_ts, "by": "alice"},
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/2.json",
        json={"id": 2, "title": "Best sourdough recipe", "url": "https://x.com/2", "time": now_ts, "by": "bob"},
    )
    httpx_mock.add_response(
        url="https://hacker-news.firebaseio.com/v0/item/3.json",
        json={"id": 3, "title": "New LLM benchmark released", "url": "https://x.com/3", "time": now_ts, "by": "carol"},
    )

    c = HackerNewsCollector()
    items = await c.fetch_since(datetime.now(timezone.utc) - timedelta(hours=2))
    titles = [i.title for i in items]
    assert "Anthropic launches Claude 5" in titles
    assert "New LLM benchmark released" in titles
    assert "Best sourdough recipe" not in titles
