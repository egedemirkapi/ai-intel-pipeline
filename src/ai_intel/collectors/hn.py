import logging
from datetime import datetime, timezone

import httpx

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)

AI_KEYWORDS = {
    "ai",
    "ml",
    "llm",
    "agent",
    "anthropic",
    "openai",
    "claude",
    "gpt",
    "gemini",
    "transformer",
    "deepseek",
    "mistral",
    "meta-llama",
    "llama",
    "rag",
    "embedding",
    "fine-tun",
    "diffusion",
    "neural",
    "deep learning",
    "machine learning",
    "artificial intelligence",
    "copilot",
    "cursor",
    "perplexity",
    "groq",
    "cerebras",
    "huggingface",
    "langchain",
    "vector db",
}

HN_BASE = "https://hacker-news.firebaseio.com/v0"
TOP_STORIES_URL = f"{HN_BASE}/topstories.json"
MAX_IDS = 100


def _is_ai_relevant(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in AI_KEYWORDS)


class HackerNewsCollector(Collector):
    name = "hn"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        results: list[RawItem] = []
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(TOP_STORIES_URL)
                resp.raise_for_status()
                story_ids: list[int] = resp.json()[:MAX_IDS]
            except Exception as exc:
                logger.error("HN: failed to fetch top stories: %s", exc)
                return results

            for story_id in story_ids:
                try:
                    item_url = f"{HN_BASE}/item/{story_id}.json"
                    r = await client.get(item_url)
                    r.raise_for_status()
                    data = r.json()

                    title = data.get("title", "")
                    if not _is_ai_relevant(title):
                        continue

                    published_ts = data.get("time")
                    if published_ts is None:
                        continue
                    published_at = datetime.fromtimestamp(published_ts, tz=timezone.utc)

                    if published_at < since:
                        continue

                    url = data.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
                    results.append(
                        RawItem(
                            url=url,
                            title=title,
                            published_at=published_at,
                            body=None,
                            author=data.get("by"),
                            raw={"hn_id": story_id, "score": data.get("score")},
                        )
                    )
                except Exception as exc:
                    logger.warning("HN: failed to fetch item %s: %s", story_id, exc)
                    continue

        return results
