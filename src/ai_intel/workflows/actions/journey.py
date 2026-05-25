"""Action: run a multi-step browser journey via the journey agent.

Lets a workflow include a multi-step navigation step — e.g. *"open
the study tabs, then navigate to Chemistry, then create a NotebookLM
notebook with the exam materials"* as a single line in a routine.
Thin wrapper over the ``journey`` agent, mirroring the pattern of
``browser.navigate``.

Use this in a workflow when you want a saved/scheduled multi-step
flow (the routine engine + cron triggers). For one-off voice/chat
requests, the chat tool ``journey.run`` (in ``brain/tools.py``)
exposes the same agent.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def action_journey_run(
    engine,
    *,
    task: str | None = None,
    url: str = "",
) -> dict:
    """Run the journey agent to complete a multi-step browser task.

    Args:
        task: natural-language high-level task ("go to Classroom, find
              the Chemistry exam, download the materials, and create a
              new NotebookLM notebook with them"). Required.
        url:  optional starting URL hint for the first substep.
    """
    from ai_intel.agents import AGENT_REGISTRY

    if not task:
        return {"error": "no task provided"}
    fn = AGENT_REGISTRY.get("journey")
    if fn is None:
        return {"error": "journey agent unavailable"}
    try:
        result = await fn(engine, task=task, url=url)
    except Exception as exc:  # noqa: BLE001 — surface as a step error
        logger.warning("journey.run: journey agent raised: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
    out = result or {}
    return {
        "summary": out.get("summary", "(no summary)"),
        "cost_usd": out.get("cost_usd", 0.0),
        "output_pointer": out.get("output_pointer"),
    }
