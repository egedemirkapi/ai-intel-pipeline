import logging
from pathlib import Path
from typing import Any

from ai_intel.collectors.base import Collector
from ai_intel.collectors.hn import HackerNewsCollector
from ai_intel.collectors.product_hunt import ProductHuntCollector
from ai_intel.collectors.rss import RSSCollector
from ai_intel.collectors.watchlist import WatchlistCollector

logger = logging.getLogger(__name__)

# (source_id, feed_url, filter_ai)
RSS_FEEDS: dict[str, tuple[str, str, bool]] = {
    "rss_techcrunch": ("techcrunch", "https://techcrunch.com/feed/", True),
    "rss_verge": ("verge", "https://www.theverge.com/rss/index.xml", True),
    "rss_venturebeat": ("venturebeat", "https://venturebeat.com/feed/", True),
    "rss_a16z": ("a16z", "https://a16z.com/feed", False),
    "rss_yc": ("yc", "https://www.ycombinator.com/blog/rss", False),
    "rss_anthropic": ("anthropic", "https://www.anthropic.com/news/feed.xml", False),
    "rss_openai": ("openai", "https://openai.com/news/rss.xml", False),
    "rss_deepmind": ("deepmind", "https://deepmind.google/blog/feed/basic", False),
    "rss_stratechery": ("stratechery", "https://stratechery.com/feed/", True),
    "rss_pragmatic_engineer": ("pragmatic_engineer", "https://blog.pragmaticengineer.com/rss/", False),
    "rss_latent_space": ("latent_space", "https://www.latent.space/feed", False),
    "rss_crunchbase": ("crunchbase", "https://news.crunchbase.com/feed/", True),
}


def build_collectors_from_config(cfg: dict[str, Any]) -> list[Collector]:
    enabled: list[str] = cfg.get("sources", {}).get("enabled", [])
    collectors: list[Collector] = []

    for src_id in enabled:
        try:
            if src_id == "hn":
                collectors.append(HackerNewsCollector())
            elif src_id == "product_hunt":
                collectors.append(ProductHuntCollector())
            elif src_id == "watchlist":
                collectors.append(WatchlistCollector(watchlist_path=Path("config/watchlist.txt")))
            elif src_id in RSS_FEEDS:
                source_id, feed_url, filter_ai = RSS_FEEDS[src_id]
                collectors.append(RSSCollector(source_id=source_id, feed_url=feed_url, filter_ai=filter_ai))
            else:
                logger.warning("Registry: unknown source id '%s', skipping", src_id)
        except Exception as exc:
            logger.error("Registry: failed to build collector '%s': %s", src_id, exc)

    return collectors
