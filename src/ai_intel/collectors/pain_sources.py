"""Pain-source collector — surfaces what people are *missing* / frustrated by.

The proposer agent (Phase 8) cross-references new tech signals with these
pains to draft candidate ideas. We piggyback on HN's Algolia search API
to find specific "Ask HN" thread types that are known pain veins:

  - "Ask HN: What do you wish existed?"  — direct wishes
  - "Ask HN: What's a problem you'd pay to solve?"
  - "Ask HN: What's your biggest pain at work?"
  - "Ask HN: What would you build if you had time?"

We tag these items with source="pain_source" so the proposer can filter
on Item.source == "pain_source" when looking for inspiration.

Quality note: these threads have a high signal-to-noise ratio because
they're explicitly soliciting unmet needs. Comments under each thread
are even better but we don't pull comment bodies here — the title +
top-level discussion captured by the Algolia result is enough for
embedding-based matching.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)

ALGOLIA_URL = "https://hn.algolia.com/api/v1/search_by_date"

# Each query becomes one Algolia search. Kept tight so total request
# count stays modest (one collector run = len(QUERIES) requests).
PAIN_QUERIES: tuple[str, ...] = (
    "Ask HN What do you wish existed",
    "Ask HN problem would you pay",
    "Ask HN biggest pain",
    "Ask HN what would you build",
    "Ask HN what's missing",
    "Ask HN frustrating tool",
    "Ask HN whats broken",
)

HITS_PER_QUERY = 30  # Algolia default page size


class PainSourcesCollector(Collector):
    name = "pain_source"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        since_epoch = int(since.timestamp())
        results: list[RawItem] = []
        seen_ids: set[int] = set()

        async with httpx.AsyncClient(timeout=30) as client:
            for q in PAIN_QUERIES:
                try:
                    r = await client.get(
                        ALGOLIA_URL,
                        params={
                            "query": q,
                            "tags": "story",
                            "numericFilters": f"created_at_i>{since_epoch}",
                            "hitsPerPage": HITS_PER_QUERY,
                        },
                    )
                    r.raise_for_status()
                    hits = r.json().get("hits", [])
                except Exception as exc:
                    logger.warning("pain_sources: query %r failed: %s", q, exc)
                    continue

                for hit in hits:
                    story_id = hit.get("objectID")
                    try:
                        sid_int = int(story_id) if story_id else None
                    except (TypeError, ValueError):
                        sid_int = None
                    if sid_int is None or sid_int in seen_ids:
                        continue

                    title = hit.get("title") or hit.get("story_title") or ""
                    if not title.lower().startswith("ask hn"):
                        # Filter out tangential matches; we only want the
                        # explicit "Ask HN" framing where intent is pain-mining.
                        continue

                    created_at_i = hit.get("created_at_i")
                    if created_at_i is None:
                        continue
                    published_at = datetime.fromtimestamp(created_at_i, tz=timezone.utc)
                    if published_at < since:
                        continue

                    # Algolia gives a story_text (the body of the Ask HN post)
                    # when present; otherwise just the title.
                    body = hit.get("story_text") or ""

                    item_url = (
                        hit.get("url")
                        or f"https://news.ycombinator.com/item?id={story_id}"
                    )
                    seen_ids.add(sid_int)
                    results.append(
                        RawItem(
                            url=item_url,
                            title=title,
                            published_at=published_at,
                            body=body or None,
                            author=hit.get("author"),
                            raw={
                                "hn_id": sid_int,
                                "points": hit.get("points"),
                                "num_comments": hit.get("num_comments"),
                                "pain_query": q,
                            },
                        )
                    )

        return results
