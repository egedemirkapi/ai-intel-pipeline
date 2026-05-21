"""Action: open the freshest tech-news articles in the browser.

The brief *lists* tech news; this opens the actual article pages. Wired
up two ways, so the user controls it:
  - as a chat / voice command — "open the top news"
  - as a routine step — add a ``news.open`` step to any workflow (e.g.
    the wake-up routine) via the dashboard routine editor.
"""
from __future__ import annotations

import logging

from ai_intel.workflows.actions.tabs import action_tabs_open_set

logger = logging.getLogger(__name__)


async def action_news_open(engine, *, count: int = 5, hours: int = 48) -> dict:
    """Open the ``count`` freshest tech-news articles as browser tabs.

    Args:
        count: how many articles to open (clamped to 1-10).
        hours: how far back "fresh" news is drawn from.

    Returns the articles opened + a summary.
    """
    # Reuse the brief's recency ranking so "the news" means the same
    # thing whether it is spoken, shown on the dashboard, or opened here.
    from ai_intel.think.brief import _top_news

    count = max(1, min(int(count or 5), 10))
    news = _top_news(engine, hours=hours, limit=count)
    articles = [
        {"title": n["title"], "url": n["url"]}
        for n in news if n.get("url")
    ]
    if not articles:
        return {"opened": 0, "articles": [], "summary": "no recent news to open"}

    result = await action_tabs_open_set(engine, urls=[a["url"] for a in articles])
    opened = result.get("opened", 0)
    logger.info("news.open: opened %d/%d article tabs", opened, len(articles))
    return {
        "opened": opened,
        "articles": articles,
        "summary": f"opened {opened} news article{'' if opened == 1 else 's'}",
    }
