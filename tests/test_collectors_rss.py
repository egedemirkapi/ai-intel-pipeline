from datetime import datetime, timezone
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from ai_intel.collectors.rss import RSSCollector

FEED_URL = "https://example.com/feed.xml"
FIXTURE = Path(__file__).parent / "fixtures" / "sample_feed.xml"


@pytest.fixture
def feed_xml() -> bytes:
    return FIXTURE.read_bytes()


@pytest.mark.asyncio
async def test_rss_filters_by_recency(httpx_mock: HTTPXMock, feed_xml: bytes):
    httpx_mock.add_response(url=FEED_URL, content=feed_xml)
    c = RSSCollector(source_id="sample", feed_url=FEED_URL, filter_ai=False)
    # since=09:00 → both items (10:00 and 11:00 are after)
    since_early = datetime(2026, 5, 17, 9, 0, 0, tzinfo=timezone.utc)
    items = await c.fetch_since(since_early)
    assert len(items) == 2


@pytest.mark.asyncio
async def test_rss_filters_by_recency_mid(httpx_mock: HTTPXMock, feed_xml: bytes):
    httpx_mock.add_response(url=FEED_URL, content=feed_xml)
    c = RSSCollector(source_id="sample", feed_url=FEED_URL, filter_ai=False)
    # since=10:30 → only 11:00 item
    since_mid = datetime(2026, 5, 17, 10, 30, 0, tzinfo=timezone.utc)
    items = await c.fetch_since(since_mid)
    assert len(items) == 1
    assert items[0].url == "https://example.com/2"


@pytest.mark.asyncio
async def test_rss_filters_ai_keywords(httpx_mock: HTTPXMock, feed_xml: bytes):
    httpx_mock.add_response(url=FEED_URL, content=feed_xml)
    c = RSSCollector(source_id="sample", feed_url=FEED_URL, filter_ai=True)
    since_early = datetime(2026, 5, 17, 9, 0, 0, tzinfo=timezone.utc)
    items = await c.fetch_since(since_early)
    titles = [i.title for i in items]
    assert "Anthropic announces new model" in titles
    assert "Generic tech news" not in titles
