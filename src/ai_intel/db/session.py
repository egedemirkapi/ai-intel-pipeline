from pathlib import Path

from sqlalchemy import event
from sqlmodel import SQLModel, create_engine


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


def init_db(engine) -> None:
    # Import models so SQLModel sees them
    from ai_intel.db import models  # noqa: F401
    SQLModel.metadata.create_all(engine)
