import logging
import os
from datetime import datetime, timezone

import httpx

from ai_intel.collectors.base import Collector, RawItem

logger = logging.getLogger(__name__)

PH_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"

QUERY = """
query RecentPosts($postedAfter: DateTime!) {
  posts(postedAfter: $postedAfter, order: NEWEST) {
    edges {
      node {
        id
        name
        tagline
        url
        createdAt
        user { name }
      }
    }
  }
}
"""


class ProductHuntCollector(Collector):
    name = "product_hunt"

    async def fetch_since(self, since: datetime) -> list[RawItem]:
        token = os.environ.get("PRODUCT_HUNT_TOKEN")
        if not token:
            logger.warning("ProductHunt: PRODUCT_HUNT_TOKEN not set, skipping")
            return []

        results: list[RawItem] = []
        posted_after = since.strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    PH_GRAPHQL_URL,
                    json={"query": QUERY, "variables": {"postedAfter": posted_after}},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.error("ProductHunt: request failed: %s", exc)
            return results

        edges = data.get("data", {}).get("posts", {}).get("edges", [])
        for edge in edges:
            try:
                node = edge["node"]
                title = f"{node['name']} — {node['tagline']}"
                created_at = datetime.fromisoformat(
                    node["createdAt"].replace("Z", "+00:00")
                )
                author = node.get("user", {}).get("name")
                results.append(
                    RawItem(
                        url=node["url"],
                        title=title,
                        published_at=created_at,
                        body=None,
                        author=author,
                        raw={"ph_id": node["id"]},
                    )
                )
            except Exception as exc:
                logger.warning("ProductHunt: error processing node: %s", exc)
                continue

        return results
