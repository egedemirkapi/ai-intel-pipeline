from datetime import datetime, timezone
from sqlmodel import Session, SQLModel, create_engine

from ai_intel.db.models import Item, Digest


def test_item_round_trip():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        item = Item(
            source="hn",
            url="https://example.com/1",
            url_hash="abc123",
            title="Test item",
            published_at=datetime.now(timezone.utc),
            collected_at=datetime.now(timezone.utc),
        )
        session.add(item)
        session.commit()
        session.refresh(item)
        assert item.id is not None


def test_digest_round_trip():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        digest = Digest(
            window_start=datetime.now(timezone.utc),
            window_end=datetime.now(timezone.utc),
            items_considered=100,
            items_selected=50,
        )
        session.add(digest)
        session.commit()
        session.refresh(digest)
        assert digest.id is not None
