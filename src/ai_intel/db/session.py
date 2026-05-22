import logging
from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlmodel import SQLModel, create_engine

logger = logging.getLogger(__name__)


def get_engine(db_path: Path):
    """Return a SQLModel engine pointing at ``db_path``.

    WAL mode is enabled on every connection so concurrent readers don't
    block writers (the collector, embedder, and agents can all touch the
    DB at once without bouncing off SQLite's default rollback-journal
    locking). Per-connection PRAGMA via event listener is the SQLAlchemy-
    standard pattern — setting it once in ``init_db`` isn't enough
    because connections in the pool open lazily.
    """
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _conn_record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def _add_missing_columns(engine) -> None:
    """Add model columns missing from already-existing tables.

    ``create_all()`` issues ``CREATE TABLE IF NOT EXISTS`` — it builds
    brand-new tables but never alters one that already exists. A column
    added to an existing model (e.g. ``Embedding.recipe_id``) is then
    silently absent from the live DB until a query hits it and SQLite
    raises ``no such column``. This closes that gap with additive
    ``ALTER TABLE ADD COLUMN`` for nullable columns. A new NOT NULL
    column still needs a hand-written migration (what value for the
    existing rows?) — it is logged, not applied.
    """
    inspector = inspect(engine)
    live_tables = set(inspector.get_table_names())
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in live_tables:
            continue  # brand-new table — create_all() already built it
        live_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in live_cols:
                continue
            if not column.nullable:
                logger.warning(
                    "db: %s.%s missing and NOT NULL — needs a manual "
                    "migration; skipping", table.name, column.name,
                )
                continue
            col_type = column.type.compile(engine.dialect)
            ddl = (f'ALTER TABLE "{table.name}" '
                   f'ADD COLUMN "{column.name}" {col_type}')
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("db: added missing column %s.%s (%s)",
                            table.name, column.name, col_type)
            except Exception as exc:  # noqa: BLE001 — log, don't crash startup
                logger.error("db: could not add column %s.%s — %s",
                              table.name, column.name, exc)


def init_db(engine) -> None:
    # Import models so SQLModel sees them
    from ai_intel.db import models  # noqa: F401
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)
