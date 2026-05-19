"""Tests for the pain_sources collector — mocked Algolia responses."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_intel.collectors.pain_sources import (
    ALGOLIA_URL,
    PAIN_QUERIES,
    PainSourcesCollector,
)


def _algolia_response(hits: list[dict]) -> dict:
    return {"hits": hits, "nbHits": len(hits)}


@pytest.mark.asyncio
async def test_collector_extracts_ask_hn_threads(httpx_mock):
    """Each PAIN_QUERY gets an Algolia call; we deduplicate by HN id."""
    now = int(datetime.now(timezone.utc).timestamp())

    common_hit = {
        "objectID": "1",
        "title": "Ask HN: What do you wish existed in 2026?",
        "story_text": "Tooling for X is broken.",
        "created_at_i": now - 60,
        "author": "alice",
        "points": 80,
        "num_comments": 40,
        "url": None,
    }
    only_in_second = {
        "objectID": "2",
        "title": "Ask HN: biggest pain at your day job?",
        "story_text": "Meetings, reporting, meetings.",
        "created_at_i": now - 120,
        "author": "bob",
        "points": 50,
        "num_comments": 22,
        "url": None,
    }
    not_ask_hn = {  # Should be filtered out: title doesn't start with "Ask HN"
        "objectID": "3",
        "title": "I built X over the weekend",
        "story_text": "...",
        "created_at_i": now - 90,
        "author": "carol",
        "points": 5,
        "num_comments": 0,
        "url": "https://example.com/x",
    }
    too_old = {
        "objectID": "4",
        "title": "Ask HN: ancient question",
        "story_text": "x",
        "created_at_i": now - 86400 * 30,  # 30 days ago
        "author": "old",
        "points": 1,
        "num_comments": 0,
        "url": None,
    }

    httpx_mock.add_response(json=_algolia_response([common_hit, not_ask_hn]))
    httpx_mock.add_response(json=_algolia_response([common_hit, only_in_second, too_old]))
    for _ in range(len(PAIN_QUERIES) - 2):
        httpx_mock.add_response(json=_algolia_response([]))

    collector = PainSourcesCollector()
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    results = await collector.fetch_since(cutoff)

    ids = sorted(int(r.raw["hn_id"]) for r in results)
    assert ids == [1, 2]
    titles = {r.title for r in results}
    assert "Ask HN: What do you wish existed in 2026?" in titles
    bodies = {r.body for r in results}
    assert "Tooling for X is broken." in bodies


@pytest.mark.asyncio
async def test_collector_uses_fallback_url_when_url_missing(httpx_mock):
    now = int(datetime.now(timezone.utc).timestamp())
    httpx_mock.add_response(json=_algolia_response([{
        "objectID": "42",
        "title": "Ask HN: what's missing?",
        "story_text": None,
        "created_at_i": now - 30,
        "author": "x",
    }]))
    for _ in range(len(PAIN_QUERIES) - 1):
        httpx_mock.add_response(json=_algolia_response([]))

    collector = PainSourcesCollector()
    results = await collector.fetch_since(datetime.now(timezone.utc) - timedelta(days=7))
    assert len(results) == 1
    assert "news.ycombinator.com/item?id=42" in results[0].url


@pytest.mark.asyncio
async def test_collector_survives_one_query_failing(httpx_mock):
    now = int(datetime.now(timezone.utc).timestamp())
    httpx_mock.add_response(status_code=500)
    httpx_mock.add_response(json=_algolia_response([{
        "objectID": "9",
        "title": "Ask HN: what is broken?",
        "story_text": "lots of things",
        "created_at_i": now - 30,
        "author": "z",
    }]))
    for _ in range(len(PAIN_QUERIES) - 2):
        httpx_mock.add_response(json=_algolia_response([]))

    collector = PainSourcesCollector()
    results = await collector.fetch_since(datetime.now(timezone.utc) - timedelta(days=7))
    assert len(results) == 1
    assert int(results[0].raw["hn_id"]) == 9
