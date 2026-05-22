from pathlib import Path

from sqlalchemy import inspect, text

from ai_intel.db.session import get_engine, init_db


def test_init_db_creates_file(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = get_engine(db_path)
    init_db(engine)
    assert db_path.exists()


def test_init_db_backfills_column_missing_from_existing_table(tmp_path: Path):
    """create_all() never alters an existing table — init_db() must backfill
    a model column added after that table already existed. Regression for
    `no such column: embedding.recipe_id` (commit f0d6cee)."""
    db_path = tmp_path / "old.db"
    engine = get_engine(db_path)
    # Simulate a pre-existing `embedding` table on the OLD schema — before
    # Embedding.recipe_id was added to the model.
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE embedding ("
            "id INTEGER PRIMARY KEY, item_id INTEGER, note_id INTEGER, "
            "model VARCHAR, dim INTEGER, vector BLOB, created_at DATETIME)"
        ))
    init_db(engine)  # create_all() skips the existing table; migration backfills
    cols = {c["name"] for c in inspect(engine).get_columns("embedding")}
    assert "recipe_id" in cols, f"recipe_id not backfilled; got {sorted(cols)}"
    init_db(engine)  # idempotent — a second run must not raise
