"""Action: drive the browser to complete a task (the navigator agent).

Lets a workflow / routine include an in-app navigation step — e.g.
"open my study tabs, then in Classroom go to the Chemistry exam page".
A thin wrapper over the `navigator` agent.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def action_browser_navigate(
    engine,
    *,
    task: str | None = None,
    url: str = "",
) -> dict:
    """Run the navigator agent to complete an in-app task.

    Args:
        task: natural-language task, e.g. "create a notebook in NotebookLM".
        url:  optional starting URL.
    """
    from ai_intel.agents import AGENT_REGISTRY

    if not task:
        return {"error": "no task provided"}
    fn = AGENT_REGISTRY["navigator"]
    try:
        result = await fn(engine, task=task, url=url)
    except Exception as exc:  # noqa: BLE001 — surface as a step error
        logger.warning("browser.navigate: navigator raised: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
    out = result or {}
    return {
        "summary": out.get("summary", "(no summary)"),
        "cost_usd": out.get("cost_usd", 0.0),
    }
