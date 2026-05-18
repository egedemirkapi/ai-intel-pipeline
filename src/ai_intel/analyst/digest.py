import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from sqlmodel import Session, select

from ai_intel.db.models import Item
from ai_intel.enrichment.enrich import _strip_markdown_fences
from ai_intel.llm import get_anthropic_client

logger = logging.getLogger(__name__)

PROMPT_PATH = Path("prompts/analyst.txt")


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


async def generate_digest(
    engine,
    window_start: datetime,
    window_end: datetime,
    model: str,
    top_n: int = 50,
    ai_relevance_threshold: float = 0.3,
) -> dict:
    # Step 1: Pull eligible items
    with Session(engine) as s:
        stmt = (
            select(Item)
            .where(Item.published_at >= window_start)
            .where(Item.published_at <= window_end)
            .where(Item.ai_relevance >= ai_relevance_threshold)
            .where(Item.sent_in_digest_at.is_(None))
        )
        items = s.exec(stmt).all()

    if not items:
        return {"summary": "No items in window.", "top_items": [], "items_considered": 0}

    # Step 2: Build payload for Opus
    payload = [
        {
            "item_id": i.id,
            "title": i.title,
            "source": i.source,
            "url": i.url,
            "classification": i.classification,
            "pre_score": i.pre_score,
            "entities": json.loads(i.entities_json or "{}"),
            "body": (i.body or "")[:300],
        }
        for i in items
    ]

    client = get_anthropic_client()
    system_prompt = _load_prompt()

    def _prescore_fallback(reason: str) -> dict:
        sorted_items = sorted(items, key=lambda x: x.pre_score or 0, reverse=True)[:top_n]
        return {
            "summary": f"Limited analysis — {reason}. Fell back to pre-score ranking from Haiku enrichment.",
            "top_items": [
                {"item_id": i.id, "rank": idx + 1, "why_it_matters": ""}
                for idx, i in enumerate(sorted_items)
            ],
            "items_considered": len(items),
        }

    logger.info(f"Calling analyst model: {model} with {len(payload)} items")
    # Outer retry layer on top of SDK retries. The SDK retries 5x internally
    # for transient errors, but DNS issues sometimes persist longer than the
    # SDK's backoff window. Three outer attempts spaced 30/60s give the
    # network real recovery time before we give up and fall back.
    resp = None
    last_error_kind = None
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=model,
                # 47 items × ~150 tokens of "why it matters" each + summary
                # easily exceeds 8192. Haiku 4.5 supports 64k output; 16384
                # is comfortable headroom without burning the quota.
                max_tokens=16384,
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Items to rank:\n{json.dumps(payload)}\n\n"
                        "REMINDER: respond with ONLY the JSON object. "
                        "Your response must start with `{` and end with `}`. "
                        "No prose, no markdown fences, no commentary."
                    ),
                }],
            )
            break
        except anthropic.RateLimitError as e:
            # Don't retry rate-limits — they won't clear in 30s. Fall back now.
            logger.error(f"Analyst model {model} rate-limited (429): {e}")
            return _prescore_fallback(f"analyst model {model} rate-limited (429)")
        except anthropic.APIConnectionError as e:
            last_error_kind = f"APIConnectionError"
            wait = 30 * (attempt + 1)
            logger.warning(
                f"Analyst APIConnectionError (attempt {attempt+1}/3): {e}. "
                f"Waiting {wait}s before retry."
            )
            if attempt < 2:
                await asyncio.sleep(wait)
        except anthropic.APIError as e:
            logger.error(f"Analyst model {model} API error: {e}")
            return _prescore_fallback(f"analyst model {model} API error ({type(e).__name__})")
        except Exception as e:
            logger.exception(f"Unexpected analyst failure ({model}): {e}")
            return _prescore_fallback(f"unexpected analyst failure with {model} ({type(e).__name__})")

    if resp is None:
        return _prescore_fallback(
            f"analyst {model} unreachable after 3 outer retries ({last_error_kind}) — "
            f"network/DNS issue suspected"
        )

    raw_text = resp.content[0].text
    cleaned = _strip_markdown_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"Analyst {model} returned non-JSON: {e}\nRaw: {raw_text[:1000]}")
        return _prescore_fallback(f"analyst {model} output unparseable")

    # Step 3: Validate — strip hallucinated and out-of-window items
    # Build lookup keyed by id for items that passed the SQL filter
    valid_ids = {i.id: i for i in items}
    validated = []
    for entry in parsed.get("top_50", []):
        iid = entry.get("item_id")
        # First guard: item_id must exist in DB within the eligible set
        if iid not in valid_ids:
            logger.warning(f"Opus hallucinated item_id {iid} — stripped")
            continue
        # Second guard: redundant window re-check (defence-in-depth against SQL bypass)
        item = valid_ids[iid]
        pub = item.published_at
        # SQLite returns naive datetimes; normalise for comparison
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        ws = window_start if window_start.tzinfo else window_start.replace(tzinfo=timezone.utc)
        we = window_end if window_end.tzinfo else window_end.replace(tzinfo=timezone.utc)
        if not (ws <= pub <= we):
            logger.warning(f"Item {iid} outside window — stripped")
            continue
        validated.append(entry)

    return {
        "summary": parsed.get("summary", ""),
        "top_items": validated[:top_n],
        "items_considered": len(items),
    }
