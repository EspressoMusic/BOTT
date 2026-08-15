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
    _migrate_missing_columns()


def _migrate_missing_columns() -> None:
    """create_all only adds missing TABLES, not missing COLUMNS on tables that
    already exist — so columns added to a model after the DB file was first
    created (like Trade.initial_risk / target_extended) need a manual
    ALTER TABLE here, or they'd silently stay absent on this machine's
    existing bott.db."""
    with engine.connect() as conn:
        existing = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(trade)")}
        if "initial_risk" not in existing:
            conn.exec_driver_sql("ALTER TABLE trade ADD COLUMN initial_risk FLOAT")
        if "target_extended" not in existing:
            conn.exec_driver_sql("ALTER TABLE trade ADD COLUMN target_extended BOOLEAN DEFAULT 0")

        existing_thoughtlog = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(thoughtlog)")}
        if "instrument" not in existing_thoughtlog:
            conn.exec_driver_sql("ALTER TABLE thoughtlog ADD COLUMN instrument VARCHAR DEFAULT ''")

        conn.commit()


def get_session() -> Session:
    return Session(engine)
