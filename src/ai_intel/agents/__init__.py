"""Agent fleet — runtime, observability, and individual workers.

Phase 7 (this commit): runtime + observability + @agent decorator.
Phase 8: saturator / proposer / evaluator workers.

Public surface:
    @agent("name")           — decorator that records an AgentRun
    call_llm(...)            — cost-aware OAuth-first LLM router
    recent_runs(agent_id)    — observability query
    summary_for_user()       — human-readable fleet status line
"""
from ai_intel.agents.decorator import agent
from ai_intel.agents.observability import (
    recent_runs,
    last_completed,
    summary_for_user,
)
from ai_intel.agents.runtime import (
    AuthMode,
    LLMResponse,
    call_llm,
    estimate_cost_usd,
)

__all__ = [
    "agent",
    "AuthMode",
    "LLMResponse",
    "call_llm",
    "estimate_cost_usd",
    "recent_runs",
    "last_completed",
    "summary_for_user",
]
