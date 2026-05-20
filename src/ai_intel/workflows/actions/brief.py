"""Action: compose the daily briefing.

Wraps ``think.build_brief`` so a workflow step can assemble the brief
and hand its spoken summary to a following ``notify`` step.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def action_brief_compose(engine) -> dict:
    """Assemble the briefing. Returns the full brief plus a ``summary``
    (the spoken string) for template interpolation by later steps."""
    from ai_intel.think.brief import build_brief

    brief = await build_brief(engine)
    return {
        "summary": brief["spoken"],
        "news_count": len(brief["news"]),
        "brief": brief,
    }
