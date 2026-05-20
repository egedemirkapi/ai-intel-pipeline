"""Agent fleet — runtime, observability, and individual workers.

Phase 7: runtime + observability + @agent decorator.
Phase 8: saturator / proposer / evaluator workers.
Phase 9: synthesizer — ecosystem-level trend recognition (the "don't
         react to every update; reason deeply across the whole feed"
         layer that sits upstream of the proposer).

Public surface:
    @agent("name")           — decorator that records an AgentRun
    call_llm(...)            — cost-aware OAuth-first LLM router
    recent_runs(agent_id)    — observability query
    summary_for_user()       — human-readable fleet status line

    saturator(engine, topic=...)        — assess saturation for a topic
    synthesizer(engine, days=...)       — find convergent trends in intel
    proposer(engine, persona_id=...)    — draft one IdeaCandidate
    evaluator(engine, candidate_id=...) — multi-persona critique + score
"""
from ai_intel.agents.decorator import agent
from ai_intel.agents.evaluator import evaluator
from ai_intel.agents.ideation import weekly_ideation
from ai_intel.agents.observability import (
    recent_runs,
    last_completed,
    summary_for_user,
)
from ai_intel.agents.proposer import proposer
from ai_intel.agents.runtime import (
    AuthMode,
    LLMResponse,
    call_llm,
    estimate_cost_usd,
)
from ai_intel.agents.saturator import saturator
from ai_intel.agents.synthesizer import synthesizer

# Registry so the CLI can look up agents by id without static if/else.
AGENT_REGISTRY = {
    "saturator":       saturator,
    "synthesizer":     synthesizer,
    "proposer":        proposer,
    "evaluator":       evaluator,
    "weekly_ideation": weekly_ideation,
}

__all__ = [
    "agent",
    "AGENT_REGISTRY",
    "AuthMode",
    "LLMResponse",
    "call_llm",
    "estimate_cost_usd",
    "recent_runs",
    "last_completed",
    "summary_for_user",
    "saturator",
    "synthesizer",
    "proposer",
    "evaluator",
    "weekly_ideation",
]
