"""Action: open the freshest tech-news articles in the browser.

The brief *lists* tech news; this opens the actual article pages. Wired
up two ways, so the user controls it:
  - as a chat / voice command — "open the top news"
  - as a routine step — add a ``news.open`` step to any workflow (e.g.
    the wake-up routine) via the dashboard routine editor.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ai_intel.workflows.actions.tabs import action_tabs_open_set

logger = logging.getLogger(__name__)


async def action_news_open(
    engine,
    *,
    count: int = 5,
    hours: int = 48,
    min_ai_relevance: float = 0.0,
) -> dict:
    """Open the ``count`` freshest tech-news articles as browser tabs.

    Args:
        count: how many articles to open (clamped to 1-10).
        hours: how far back "fresh" news is drawn from.
        min_ai_relevance: filter to items scoring at least this on the
            enrichment pipeline's AI-relevance scale (0.0-1.0). Default
            0.0 = no filter (preserves the prior behavior). Use 0.5-0.7
            for "AI sector only" — the bundled ``routine`` workflow
            sets 0.6 so "run the routine" opens AI-relevant tabs rather
            than whatever happens to be most recent.

    Returns the articles opened + a summary.
    """
    # Reuse the brief's recency ranking so "the news" means the same
    # thing whether it is spoken, shown on the dashboard, or opened here.
    from ai_intel.think.brief import _top_news

    count = max(1, min(int(count or 5), 10))
    news = _top_news(
        engine,
        hours=hours,
        limit=count,
        min_ai_relevance=float(min_ai_relevance or 0.0),
    )
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


async def action_news_email_digest(
    engine, *, window_hours: int = 48, email_to=None,
) -> dict:
    """Summarize recent tech news into a PDF and email it.

    Wraps the digest pipeline (`generate_and_send_digest`): gather the
    news in the window, summarize it with the analyst model, render a
    PDF, and email it via Resend with the PDF attached. This is the
    action that powers scheduled automations like a daily news digest.

    Args:
        window_hours: how far back the news window reaches — default 48
            (today + yesterday).
        email_to: recipient(s); defaults to ``delivery.email_to`` in
            config/config.yaml.
    """
    # Lazy imports — these pull in the analyst, Playwright PDF, and the
    # mailer; keep them out of the module-level import cost.
    from ai_intel.pipeline import generate_and_send_digest
    from ai_intel.scheduler import load_config

    cfg = load_config()
    model = cfg["llm"]["analyst_model"]
    if not email_to:
        email_to = cfg["delivery"]["email_to"]

    # only_unsent=False / mark_sent=False: a recurring digest summarizes the
    # whole window every run and must not consume items from other digests.
    result = dict(await generate_and_send_digest(
        engine,
        output_dir=Path("output"),
        window_hours=int(window_hours),
        model=model,
        email_to=email_to,
        only_unsent=False,
        mark_sent=False,
    ))
    if result.get("sent"):
        result["summary"] = f"emailed the news digest PDF to {email_to}"
        logger.info("news.email_digest: sent to %s", email_to)
    else:
        result["summary"] = f"news digest not sent ({result.get('reason', 'unknown')})"
        logger.warning("news.email_digest: not sent — %s", result.get("reason"))
    return result
