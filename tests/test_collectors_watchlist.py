from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from ai_intel.collectors.watchlist import WatchlistCollector

FEED_URL = "https://myblog.example.com/rss.xml"
SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>My Blog</title>
  <item>
    <title>AI article from watchlist</title>
    <link>https://myblog.example.com/ai-article</link>
    <pubDate>Sun, 17 May 2026 12:00:00 +0000</pubDate>
    <description>Something interesting.</description>
  </item>
</channel>
</rss>"""


@pytest.mark.asyncio
async def test_watchlist_reads_rss_urls(httpx_mock: HTTPXMock, tmp_path: Path):
    watchlist_file = tmp_path / "watchlist.txt"
    watchlist_file.write_text(
        f"# This is a comment\n{FEED_URL}\n\n",
        encoding="utf-8",
    )

    httpx_mock.add_response(url=FEED_URL, content=SAMPLE_XML)

    c = WatchlistCollector(watchlist_path=watchlist_file)
    since = datetime(2026, 5, 17, 9, 0, 0, tzinfo=timezone.utc)
    items = await c.fetch_since(since)
    assert len(items) == 1
    assert items[0].title == "AI article from watchlist"


@pytest.mark.asyncio
async def test_watchlist_empty_file_returns_empty(tmp_path: Path):
    watchlist_file = tmp_path / "watchlist.txt"
    watchlist_file.write_text("# only comments\n\n", encoding="utf-8")

    c = WatchlistCollector(watchlist_path=watchlist_file)
    items = await c.fetch_since(datetime.now(timezone.utc) - timedelta(hours=2))
    assert items == []
