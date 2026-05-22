"""Jarvis conversational chat loop with Anthropic tool use.

POST /chat → run_chat() → final text + history.

The loop calls Anthropic with the Brain's tool registry attached. The
model may emit tool_use blocks; we execute them via the capability-
gated ``invoke()`` and feed tool_result blocks back. Iterates until
the model returns end_turn or we hit ``max_iterations`` (safety cap).

We use the API-key path directly here. The OAuth bridge would also
work but its protocol doesn't yet support tool-use. Chat volume is
low (user-driven, ~10 turns/day) so paid Haiku spend is pennies.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ai_intel.brain.tools import (
    Tool,
    anthropic_tool_specs,
    build_registry,
    invoke,
    resolve_api_name,
)
from ai_intel.llm import get_anthropic_client

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are Jarvis, Ege's personal assistant. You have
direct, live access to:

- The startup-ideation agent fleet: saturator, synthesizer, proposer,
  evaluator, weekly_ideation (orchestrator that chains them)
- 24/7-collected tech intel (HN, Reddit, RSS feeds, Google News, etc.)
- Founder-brain corpus: Paul Graham essays, Sam Altman blog, a16z
- Failure-corpus: failory.com cemetery post-mortems
- IdeaCandidate rows with multi-persona critiques
- Automations: saved workflows you can build, run, and schedule

Behavior:
- Be direct and concise. No filler, no rambling.
- When the user asks about the fleet, call agents.status / agents.tail.
- When asked about ideas, call ideas.list (filter by status / score).
- When asked for details on an idea, call ideas.show with the id.
- When asked about emerging trends, call trends.latest.
- When asked to "run the process" / "give me ideas" / "fire the cycle",
  call agents.run with agent_id='weekly_ideation' (set n_candidates if
  the user mentions a number).
- When asked "what was I reading about X", call memory.recall.
- To open a website call web.open / news.open; to open an app call
  apps.open. For apps that have a web version (Spotify, YouTube, Gmail,
  WhatsApp, Discord, Notion, ChatGPT, Maps, Calendar) always prefer the
  webapp — leave `desktop` false. Only set `desktop: true` when the user
  explicitly says "desktop app" / "desktop application" / "installed app".
- AUTOMATIONS: when the user describes a recurring or triggered task
  ("every day...", "each morning...", "automatically email me...",
  "when I open X..."), call workflow.create. Translate plain-language
  timing into a 5-field cron string ("every day at 8am" -> "0 8 * * *").
  For a daily news-summary email, the step is news.email_digest. Use
  workflow.run to run one now, workflow.list to show them, and
  workflow.delete to remove one.
- Cite tool results inline. If a tool returns an error/refusal, say so.

Hard constraints (enforced at capability layer, not your decision):
- You cannot send a one-off email, write files, modify Google data, or
  run arbitrary shell commands directly from chat. If asked for one of
  those as a one-off, refuse in one line.
- You CAN, however, create a scheduled automation that emails (e.g. a
  daily news digest via news.email_digest) — that is the user
  explicitly setting it up, and it runs through the gated workflow
  engine. Building such an automation when asked is correct, not a
  violation.

Address Ege occasionally but not every reply. Match his register —
casual, technical, direct."""


async def run_chat(
    engine,
    user_message: str,
    *,
    model: str = "claude-haiku-4-5",
    max_iterations: int = 8,
    max_tokens_per_turn: int = 2000,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run one chat round and return the final assistant text + history.

    Args:
        engine: SQLModel engine to pass through to tool handlers.
        user_message: the user's new message text.
        model: LLM model id (default Haiku — cheap and fast for chat).
        max_iterations: safety cap on tool-use roundtrips.
        max_tokens_per_turn: per-LLM-call cap.
        history: prior messages (assistant + user + tool_result blocks).
            If None, starts fresh with just the new user message.

    Returns:
        {
            "reply": str,                # concatenated text blocks
            "history": list[message],    # full conversation incl. tools
            "tool_calls": [{name, args, result}, ...],
            "iterations": int,
            "model": str,
        }
    """
    client = get_anthropic_client()
    registry = build_registry()
    tools_spec = anthropic_tool_specs(registry)

    messages: list[dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": user_message})

    text_pieces: list[str] = []
    tool_calls_log: list[dict[str, Any]] = []
    iterations = 0

    for _ in range(max_iterations):
        iterations += 1
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens_per_turn,
            system=SYSTEM_PROMPT,
            tools=tools_spec,
            messages=messages,
        )
        # Anthropic returns content as a list of blocks (text + tool_use)
        assistant_content = []
        tool_uses = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_pieces.append(block.text)
                assistant_content.append({"type": "text", "text": block.text})
            elif btype == "tool_use":
                tool_uses.append(block)
                assistant_content.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
        messages.append({"role": "assistant", "content": assistant_content})

        if not tool_uses or resp.stop_reason == "end_turn":
            break

        # Execute each requested tool, feed results back. The model sees
        # API-safe hyphenated names; translate back to the internal
        # dotted name the registry + capability layer use.
        tool_results_msg: list[dict[str, Any]] = []
        for tu in tool_uses:
            args = tu.input or {}
            internal_name = resolve_api_name(tu.name)
            result = await invoke(registry, engine, internal_name, args)
            tool_calls_log.append({
                "name": internal_name,
                "args": args,
                "result_keys": list(result.keys()) if isinstance(result, dict) else None,
                "refused": isinstance(result, dict) and "refused" in result,
            })
            tool_results_msg.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, default=str)[:8000],
            })
        messages.append({"role": "user", "content": tool_results_msg})

    return {
        "reply": "\n\n".join(text_pieces).strip(),
        "history": messages,
        "tool_calls": tool_calls_log,
        "iterations": iterations,
        "model": model,
    }
