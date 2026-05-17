from pathlib import Path

from ai_intel.db.session import get_engine, init_db


def test_init_db_creates_file(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = get_engine(db_path)
    init_db(engine)
    assert db_path.exists()
