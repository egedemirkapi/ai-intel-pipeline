import logging
from datetime import datetime, timezone

import httpx

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)

AI_KEYWORDS = {
    # Core AI/ML terms
    "ai", "ml", "llm", "llms", "agent", "agents", "ai-",
    "model", "models", "inference", "training", "fine-tun",
    "prompt", "prompts", "prompting",
    # Labs + products
    "anthropic", "claude", "openai", "gpt", "chatgpt", "sora",
    "gemini", "google deepmind", "deepmind", "nano banana",
    "deepseek", "mistral", "meta-llama", "llama", "qwen", "yi-", "kimi",
    "grok", "xai", "x.ai",
    "stability", "stable diffusion", "midjourney", "runway", "veo", "pika",
    "huggingface", "hugging face", "scale ai", "databricks",
    "nvidia", "nvda",  # NVIDIA news drives the entire AI stack
    # Concepts
    "transformer", "rag", "embedding", "diffusion",
    "neural", "deep learning", "machine learning", "artificial intelligence",
    "reasoning model", "reasoning", "chain-of-thought", "cot ",
    "multimodal", "vision-language", "vlm ", "mixture of experts", "moe ",
    "agentic", "tool use", "tool-use", "agent infra", "function calling",
    "context window", "long context", "tokens",
    # AI startups / products / dev tools
    "copilot", "cursor", "perplexity", "groq", "cerebras", "langchain",
    "vector db", "vector database", "llamaindex", "ollama",
    "windsurf", "replit agent", "devin", "bolt.new", "v0.dev",
    "browserbase", "phidata", "crewai", "autogen", "mcp",
    "harvey", "glean", "writer", "jasper", "elevenlabs", "character.ai",
    "suno", "udio", "luma", "pika labs", "ideogram",
    # Funding / scaling signals
    "raised $", "raises $", "series a", "series b", "series c", "series d",
    "valued at", "valuation", "funding round", "venture round",
    "yc s2", "yc w2", "yc x", "ycombinator",
    "h100", "h200", "b100", "b200", "blackwell", "tpu", "trainium",
    "compute", "data center", "datacenter", "gpus",
    # Other relevant
    "rlhf", "alignment", "safety", "agi", "asi", "superintelligence",
    "code generation", "code-gen", "coding agent", "vibe code",
    "robot", "robotics", "humanoid", "autonomous",
    "chatbot", "voice ai", "speech ai", "text-to-",
}

HN_BASE = "https://hacker-news.firebaseio.com/v0"
TOP_STORIES_URL = f"{HN_BASE}/topstories.json"
NEW_STORIES_URL = f"{HN_BASE}/newstories.json"
BEST_STORIES_URL = f"{HN_BASE}/beststories.json"
MAX_IDS = 200  # was 100 — wider net for AI items


def _is_ai_relevant(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in AI_KEYWORDS)


class HackerNewsCollector(Collector):
    name = "hn"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        results: list[RawItem] = []
        async with httpx.AsyncClient(timeout=30) as client:
            # Pull from top, best, AND new — union them — gives us 3x the candidate pool
            all_ids: list[int] = []
            seen: set[int] = set()
            for label, url in [("top", TOP_STORIES_URL), ("best", BEST_STORIES_URL), ("new", NEW_STORIES_URL)]:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    for sid in resp.json()[:MAX_IDS]:
                        if sid not in seen:
                            seen.add(sid)
                            all_ids.append(sid)
                except Exception as exc:
                    logger.warning("HN: failed to fetch %s stories: %s", label, exc)

            if not all_ids:
                logger.error("HN: all story lists failed")
                return results

            for story_id in all_ids:
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
