"""Action: run a backend fleet agent from inside a workflow.

Lets a workflow (e.g. morning_brief) trigger synthesizer / proposer /
evaluator / weekly_ideation. Thin wrapper over the AGENT_REGISTRY.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def action_agent_run(
    engine,
    *,
    agent_id: str | None = None,
    args: dict | None = None,
) -> dict:
    """Run a backend agent.

    Args:
        agent_id: one of saturator/synthesizer/proposer/evaluator/
                  weekly_ideation.
        args: optional kwargs forwarded to the agent (e.g.
              {"n_candidates": 3} for weekly_ideation).
    """
    from ai_intel.agents import AGENT_REGISTRY

    if not agent_id:
        return {"error": "no agent_id provided"}
    if agent_id not in AGENT_REGISTRY:
        return {
            "error": f"unknown agent_id={agent_id!r}",
            "known": sorted(AGENT_REGISTRY.keys()),
        }
    fn = AGENT_REGISTRY[agent_id]
    kwargs = {k: v for k, v in (args or {}).items() if v is not None}
    try:
        result = await fn(engine, **kwargs)
    except TypeError as exc:
        return {"error": f"agent rejected kwargs: {exc}"}
    except Exception as exc:
        logger.warning("agent.run: %s raised: %s", agent_id, exc)
        return {"error": f"{type(exc).__name__}: {exc}"}
    out = result or {}
    return {
        "agent_id": agent_id,
        "summary": out.get("summary", "(no summary)"),
        "cost_usd": out.get("cost_usd", 0.0),
    }
