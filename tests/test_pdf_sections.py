from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session

from ai_intel.db.models import Item
from ai_intel.db.session import get_engine, init_db
from ai_intel.pdf.sections import build_sections


def test_groups_by_classification(tmp_path: Path):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        s.add(Item(id=1, source="hn", url="https://a.com", url_hash="h1",
                   title="A", published_at=now, collected_at=now, classification="funding"))
        s.add(Item(id=2, source="hn", url="https://b.com", url_hash="h2",
                   title="B", published_at=now, collected_at=now, classification="launch"))
        s.commit()

    top_items = [
        {"item_id": 1, "rank": 1, "why_it_matters": "1"},
        {"item_id": 2, "rank": 2, "why_it_matters": "2"},
    ]
    sections = build_sections(engine, top_items)
    assert "Funding" in sections
    assert "Launches" in sections
    assert len(sections["Funding"]) == 1
    assert len(sections["Launches"]) == 1


def test_empty_top_items_returns_empty(tmp_path: Path):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    sections = build_sections(engine, [])
    assert sections == {}


def test_missing_item_is_skipped(tmp_path: Path):
    engine = get_engine(tmp_path / "test.db")
    init_db(engine)
    sections = build_sections(engine, [{"item_id": 999, "rank": 1, "why_it_matters": "x"}])
    assert sections == {}
