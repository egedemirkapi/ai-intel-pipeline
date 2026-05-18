import logging
from datetime import datetime, timezone

import feedparser
import httpx

from ai_intel.collectors.base import Collector, RawItem
from ai_intel.collectors.hn import _is_ai_relevant

logger = logging.getLogger(__name__)


class RSSCollector(Collector):
    def __init__(self, source_id: str, feed_url: str, filter_ai: bool = True) -> None:
        self.source_id = source_id
        self.feed_url = feed_url
        self.filter_ai = filter_ai

    @property
    def name(self) -> str:
        return f"rss:{self.source_id}"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        results: list[RawItem] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; AI-Intel-Pipeline/0.1; +https://github.com/egedemirkapi/ai-intel-pipeline)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        }
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
                resp = await client.get(self.feed_url)
                resp.raise_for_status()
                content = resp.content
        except Exception as exc:
            logger.error("RSS[%s]: failed to fetch feed: %s", self.source_id, exc)
            return results

        feed = feedparser.parse(content)

        # Atom feeds (OpenAI, DeepMind, Stratechery, Pragmatic Engineer) often
        # only populate updated_parsed, not published_parsed. RSS 2.0 feeds
        # populate published_parsed. Fall through both, then created_parsed.
        # If a feed gives no date at all, treat the item as fresh (now).
        now_utc = datetime.now(timezone.utc)
        for entry in feed.entries:
            try:
                tup = (
                    getattr(entry, "published_parsed", None)
                    or getattr(entry, "updated_parsed", None)
                    or getattr(entry, "created_parsed", None)
                )
                if tup is None:
                    published_at = now_utc
                else:
                    published_at = datetime(*tup[:6], tzinfo=timezone.utc)

                if published_at <= since:
                    continue

                title = entry.get("title", "")
                if self.filter_ai and not _is_ai_relevant(title):
                    continue

                url = entry.get("link", "")
                body = entry.get("summary") or entry.get("description")
                author = entry.get("author")

                results.append(
                    RawItem(
                        url=url,
                        title=title,
                        published_at=published_at,
                        body=body,
                        author=author,
                        raw={"feed": self.source_id},
                    )
                )
            except Exception as exc:
                logger.warning("RSS[%s]: error processing entry: %s", self.source_id, exc)
                continue

        return results
