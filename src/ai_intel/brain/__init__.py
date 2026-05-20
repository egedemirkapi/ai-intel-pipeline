"""Jarvis Brain — the conversational + introspection layer over the fleet.

This package provides:
    app           — FastAPI service bound to 127.0.0.1:9999
    tool_registry — capability-gated tool surface the LLM can call
    event_bus     — in-process pub/sub for AgentRun fleet events
    chat_loop     — conversational LLM loop with Anthropic tool use

The Brain is the ONLY component that talks to the LLM for end-user
interaction. Backend worker agents (saturator, synthesizer, proposer,
evaluator) keep running headless via the scheduler; the Brain reads
their outputs and routes user intent to invoke them when asked.

Bind: 127.0.0.1:9999 (Tailscale ACL controls external reach; no
app-layer auth needed for personal use).
"""
from ai_intel.brain.events import (
    EventBus,
    FleetEvent,
    get_event_bus,
)
from ai_intel.brain.tools import (
    Tool,
    anthropic_tool_specs,
    build_registry,
    invoke,
)

__all__ = [
    "EventBus",
    "FleetEvent",
    "get_event_bus",
    "Tool",
    "anthropic_tool_specs",
    "build_registry",
    "invoke",
]
