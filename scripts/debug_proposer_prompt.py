"""Dry-run the proposer's context assembly — prints the assembled prompt
without calling the LLM. Lets us see what the LLM would actually see.

Usage:
    python scripts/debug_proposer_prompt.py
    python scripts/debug_proposer_prompt.py --persona sam_altman
"""
import argparse
import asyncio
import sys
from datetime import datetime, timezone

# Load .env BEFORE any ai_intel import so JARVIS_EMBEDDING_PROVIDER=voyage
# takes effect at get_embedder() time. Without this, get_embedder() returns
# FakeEmbedder, and recall() filters embeddings by model name — so
# failure_corpus items (only embedded under voyage-3) become invisible.
from dotenv import load_dotenv  # noqa: E402
load_dotenv()

# Patch the underlying API-key + OAuth callers in runtime so anything that
# bottoms out in `call_llm` short-circuits to the stub. This is safer than
# rebinding `call_llm` in each importer's namespace because both saturator
# and proposer have already captured the original name.
import ai_intel.agents.runtime as _rt  # noqa: E402
from ai_intel.agents.runtime import LLMResponse  # noqa: E402


def _stub_call_llm(messages, **kwargs):
    prompt = messages[0]["content"]
    is_proposer = "NEW TECH SIGNAL" in prompt and "differentiation" in prompt
    if is_proposer:
        print("=" * 72)
        print(f"PROPOSER PROMPT — {len(prompt)} chars (~{len(prompt) // 4} tokens)")
        print("=" * 72)
        print(prompt)
        print("=" * 72)
        return LLMResponse(
            text='{"idea":"(stub)","tech_basis":"(stub)","pain_basis":"(stub)",'
                 '"wedge":"(stub)","key_assumption":"(stub)",'
                 '"validation_step":"(stub)","why_now":"(stub)",'
                 '"differentiation":"(stub)"}',
            prompt_tokens=len(prompt) // 4,
            completion_tokens=50,
            cost_usd=0.0,
            auth_mode="api_key",
            model="stub",
        )
    # Saturator stub — return shape its parser expects
    return LLMResponse(
        text='{"score": 0.3, "competitor_count": 2, '
             '"notes": "(stubbed saturator response)", "verdict": "emerging"}',
        prompt_tokens=len(prompt) // 4,
        completion_tokens=20,
        cost_usd=0.0,
        auth_mode="api_key",
        model="stub",
    )


_rt._call_api_key = lambda messages, model, max_tokens, temperature: _stub_call_llm(messages)
_rt._call_oauth = lambda messages, model, max_tokens, temperature: _stub_call_llm(messages)

from pathlib import Path  # noqa: E402

from ai_intel.agents.proposer import proposer  # noqa: E402
from ai_intel.db.session import get_engine  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--persona", default="paul_graham")
    parser.add_argument("--db", default="data/items.db")
    args = parser.parse_args()

    engine = get_engine(Path(args.db))
    result = await proposer(engine, persona_id=args.persona)
    print(f"\nRESULT: {result.get('summary')}")


if __name__ == "__main__":
    asyncio.run(main())
