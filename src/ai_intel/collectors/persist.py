import hashlib
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from ai_intel.collectors.base import RawItem
from ai_intel.db.models import Item


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


async def persist_items(engine, source: str, items: list[RawItem]) -> int:
    inserted = 0
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        for raw in items:
            h = url_hash(raw.url)
            existing = session.exec(select(Item).where(Item.url_hash == h)).first()
            if existing:
                continue
            item = Item(
                source=source,
                url=raw.url,
                url_hash=h,
                title=raw.title,
                body=raw.body,
                author=raw.author,
                published_at=raw.published_at,
                collected_at=now,
                raw_json=json.dumps(raw.raw) if raw.raw else None,
            )
            session.add(item)
            inserted += 1
        session.commit()
    return inserted
