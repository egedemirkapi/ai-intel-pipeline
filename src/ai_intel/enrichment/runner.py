import json
import logging

from sqlmodel import Session, select

from ai_intel.db.models import Item
from ai_intel.enrichment.enrich import enrich_batch
from ai_intel.llm import get_anthropic_client

logger = logging.getLogger(__name__)


async def enrich_new_items(engine, model: str, batch_size: int = 10) -> int:
    """Process all items lacking enrichment. Returns count enriched."""
    client = get_anthropic_client()
    total = 0

    with Session(engine) as session:
        unenriched = session.exec(
            select(Item).where(Item.classification.is_(None))
        ).all()

    if not unenriched:
        return 0

    for i in range(0, len(unenriched), batch_size):
        batch = unenriched[i : i + batch_size]
        try:
            results = await enrich_batch(batch, client=client, model=model)
        except Exception as e:
            logger.error(f"Enrich batch failed: {e}")
            continue

        with Session(engine) as session:
            for item in batch:
                r = results.get(item.id)
                if not r:
                    continue
                db_item = session.get(Item, item.id)
                if db_item is None:
                    continue
                db_item.classification = r.get("classification")
                db_item.ai_relevance = r.get("ai_relevance")
                db_item.entities_json = json.dumps(r.get("entities", {}))
                db_item.pre_score = r.get("pre_score")
                db_item.skip_reason = r.get("skip_reason")
                session.add(db_item)
                total += 1
            session.commit()
    return total
