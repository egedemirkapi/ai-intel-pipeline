from pathlib import Path

from sqlmodel import SQLModel, create_engine


def get_engine(db_path: Path):
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )


def init_db(engine) -> None:
    # Import models so SQLModel sees them
    from ai_intel.db import models  # noqa: F401
    SQLModel.metadata.create_all(engine)
