"""SQLite via SQLModel. Single-user, single-machine — no need for Postgres here.
WAL mode so the strategy engine's background writes don't lock out API reads.
"""

import os

from sqlmodel import Session, SQLModel, create_engine

# Overridable so the test suite can point at an isolated database instead of
# writing into the same file the live dev server is using (see tests/conftest.py).
DATABASE_URL = os.environ.get("BOTT_DATABASE_URL", "sqlite:///./bott.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
