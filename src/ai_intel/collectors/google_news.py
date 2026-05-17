"""Google News RSS collector — search-based AI news firehose.

Google News exposes RSS for any search query. Lets us monitor hundreds of
publications without configuring each individually. Run ~5 queries per cycle.
"""

import logging
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; AI-Intel-Pipeline/0.1)"


class GoogleNewsCollector(Collector):
    """Run multiple Google News searches, union the results.

    Queries to run are passed in. Use specific phrases for higher signal —
    "AI funding", "AI startup", "LLM launch", etc.
    """

    def __init__(self, queries: list[str]):
        self.queries = queries

    @property
    def name(self) -> str:
        return "google_news"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        results: list[RawItem] = []
        headers = {"User-Agent": USER_AGENT}
        seen_urls: set[str] = set()

        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            for query in self.queries:
                # when:1d limits to last day; we'll filter to `since` more strictly below
                url = f"https://news.google.com/rss/search?q={quote_plus(query)}+when:1d&hl=en-US&gl=US&ceid=US:en"
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    feed = feedparser.parse(resp.text)
                except Exception as exc:
                    logger.warning("GoogleNews[%s] failed: %s", query, exc)
                    continue

                for entry in feed.entries:
                    try:
                        link = entry.get("link", "")
                        if not link or link in seen_urls:
                            continue
                        seen_urls.add(link)

                        tup = entry.get("published_parsed") or entry.get("updated_parsed")
                        if not tup:
                            continue
                        published_at = datetime(*tup[:6], tzinfo=timezone.utc)
                        if published_at < since:
                            continue

                        title = entry.get("title", "")
                        # Google News titles are "Title - Publisher"
                        publisher = ""
                        if " - " in title:
                            title, publisher = title.rsplit(" - ", 1)

                        results.append(
                            RawItem(
                                url=link,
                                title=title,
                                published_at=published_at,
                                body=entry.get("summary"),
                                author=publisher,
                                raw={"query": query, "publisher": publisher},
                            )
                        )
                    except Exception as exc:
                        logger.warning("GoogleNews entry parse failed: %s", exc)
                        continue

        return results
