import logging
from datetime import datetime
from typing import Any

from ai_intel.collectors.base import Collector
from ai_intel.collectors.persist import persist_items

logger = logging.getLogger(__name__)


async def run_all_collectors(
    engine,
    collectors: list[Collector],
    since: datetime,
) -> dict[str, Any]:
    result: dict[str, Any] = {"failures": []}

    for collector in collectors:
        try:
            items = await collector.fetch_since(since)
            inserted = await persist_items(engine, source=collector.name, items=items)
            result[collector.name] = inserted
            logger.info("Collector '%s': fetched %d items, inserted %d", collector.name, len(items), inserted)
        except Exception as exc:
            logger.error("Collector '%s' failed: %s", collector.name, exc)
            result["failures"].append(collector.name)

    return result
