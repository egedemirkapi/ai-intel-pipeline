"""Reddit JSON API collector — pulls AI subreddits.

Uses Reddit's public .json endpoints (no auth needed for read-only). Way more
volume than HN for AI ecosystem chatter. Run-of-the-mill rate limit: ~60/min
unauthenticated — we make 4 requests per cycle so we're well under.
"""

import logging
from datetime import datetime, timezone

import httpx

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; AI-Intel-Pipeline/0.1; +https://github.com/egedemirkapi/ai-intel-pipeline)"


class RedditCollector(Collector):
    """Pulls hot + new posts from one subreddit. Filters by min score."""

    def __init__(self, subreddit: str, min_score: int = 10):
        self.subreddit = subreddit
        self.min_score = min_score

    @property
    def name(self) -> str:
        return f"reddit:r/{self.subreddit}"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        results: list[RawItem] = []
        headers = {"User-Agent": USER_AGENT}

        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            # Pull both hot AND new — union them
            for kind in ("hot", "new"):
                url = f"https://www.reddit.com/r/{self.subreddit}/{kind}.json?limit=50"
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    logger.warning("Reddit r/%s %s: %s", self.subreddit, kind, exc)
                    continue

                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    try:
                        score = post.get("score", 0)
                        if score < self.min_score:
                            continue

                        created_utc = post.get("created_utc")
                        if not created_utc:
                            continue
                        published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)
                        if published_at < since:
                            continue

                        title = post.get("title", "")
                        # Reddit posts can be self-posts (text) or link posts
                        external_url = post.get("url_overridden_by_dest") or post.get("url")
                        permalink = post.get("permalink", "")
                        item_url = external_url if external_url and not external_url.startswith("/r/") else f"https://www.reddit.com{permalink}"

                        body = post.get("selftext") or post.get("link_flair_text")
                        author = post.get("author")

                        results.append(
                            RawItem(
                                url=item_url,
                                title=title,
                                published_at=published_at,
                                body=body,
                                author=author,
                                raw={
                                    "subreddit": self.subreddit,
                                    "score": score,
                                    "num_comments": post.get("num_comments"),
                                    "permalink": f"https://www.reddit.com{permalink}",
                                },
                            )
                        )
                    except Exception as exc:
                        logger.warning("Reddit post parse failed: %s", exc)
                        continue

        return results
