import json
import logging
import re
from pathlib import Path
from typing import Any

from ai_intel.db.models import Item

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/enrichment.txt")

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    """Strip ```json ... ``` fences that Haiku sometimes wraps responses in.

    Then, if the result still isn't valid JSON, fall back to extracting the
    first top-level {...} block — handles cases where Haiku adds prose before
    or after the JSON despite being told not to.
    """
    m = _FENCE_RE.match(text)
    candidate = m.group(1) if m else text.strip()

    # Quick path: if it parses already, return as-is.
    import json as _json
    try:
        _json.loads(candidate)
        return candidate
    except _json.JSONDecodeError:
        pass

    # Fallback: scan for the first top-level JSON value — either `{...}` (analyst)
    # or `[...]` (enrichment). Respect strings + escapes so braces inside JSON
    # string values don't throw off the depth counter.
    first_obj = candidate.find("{")
    first_arr = candidate.find("[")
    candidates_pos = [p for p in (first_obj, first_arr) if p != -1]
    if not candidates_pos:
        return candidate  # nothing to extract; caller will fail and log
    start = min(candidates_pos)
    open_ch = candidate[start]
    close_ch = "}" if open_ch == "{" else "]"

    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return candidate[start:i + 1]
    return candidate  # unmatched brackets; let caller fail cleanly


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_message(items: list[Item]) -> str:
    payload = [
        {"item_id": i.id, "title": i.title, "source": i.source, "body": (i.body or "")[:500]}
        for i in items
    ]
    return f"Items: {json.dumps(payload)}"


async def enrich_batch(
    items: list[Item], client, model: str
) -> dict[int, dict[str, Any]]:
    """Enrich a batch of items via Haiku. Returns dict keyed by item_id."""
    if not items:
        return {}

    system_prompt = _load_prompt()
    user_msg = _build_user_message(items)

    resp = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw_text = resp.content[0].text
    cleaned = _strip_markdown_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"Enrichment JSON parse failed: {e}\nRaw: {raw_text[:500]}")
        return {}

    return {entry["item_id"]: entry for entry in parsed}
