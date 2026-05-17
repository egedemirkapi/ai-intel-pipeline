from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session, select

from ai_intel.collectors.base import RawItem
from ai_intel.collectors.persist import persist_items
from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db


@pytest.mark.asyncio
async def test_persist_dedups_by_url(tmp_path: Path):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    items = [
        RawItem(url="https://example.com/a", title="A", published_at=datetime.now(timezone.utc)),
        RawItem(url="https://example.com/a", title="A again", published_at=datetime.now(timezone.utc)),
    ]
    inserted = await persist_items(engine, source="test", items=items)
    assert inserted == 1
    with Session(engine) as s:
        all_items = s.exec(select(Item)).all()
        assert len(all_items) == 1
