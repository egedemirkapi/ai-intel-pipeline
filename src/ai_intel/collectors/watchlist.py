import logging
from datetime import datetime
from pathlib import Path

from ai_intel.collectors.base import Collector, RawItem
from ai_intel.collectors.rss import RSSCollector

logger = logging.getLogger(__name__)

DEFAULT_WATCHLIST_PATH = Path("config/watchlist.txt")


class WatchlistCollector(Collector):
    name = "watchlist"

    def __init__(self, watchlist_path: Path = DEFAULT_WATCHLIST_PATH) -> None:
        self.watchlist_path = watchlist_path

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        results: list[RawItem] = []

        if not self.watchlist_path.exists():
            logger.warning("Watchlist: file not found: %s", self.watchlist_path)
            return results

        urls: list[str] = []
        for line in self.watchlist_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("http"):
                urls.append(line)
            else:
                logger.info(
                    "Watchlist: skipping non-URL entry (bare domains not supported in v1): %s",
                    line,
                )

        for url in urls:
            try:
                collector = RSSCollector(source_id=url, feed_url=url, filter_ai=False)
                items = await collector.fetch_since(since)
                results.extend(items)
            except Exception as exc:
                logger.warning("Watchlist: error fetching %s: %s", url, exc)
                continue

        return results
