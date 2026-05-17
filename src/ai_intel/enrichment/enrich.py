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
    """Strip ```json ... ``` fences that Haiku sometimes wraps responses in."""
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text.strip()


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
