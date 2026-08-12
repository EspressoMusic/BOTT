"""Points the test suite at an isolated SQLite file so tests never touch the
live dev server's bott.db (which may be running concurrently). Must set the env
var before any `app.db` import happens — conftest.py is always collected first.
"""

import os
from pathlib import Path

TEST_DB_PATH = Path(__file__).parent / "test_bott.db"
os.environ["BOTT_DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import pytest  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app.db import engine, init_db  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _setup_test_db():
    init_db()
    yield
    engine.dispose()  # release file handles before trying to delete (Windows locks open files)
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{TEST_DB_PATH}{suffix}")
        if path.exists():
            try:
                path.unlink()
            except PermissionError:
                pass  # best-effort cleanup only


@pytest.fixture(autouse=True)
def _clean_tables():
    """Every test starts against empty tables, regardless of test order or what
    other tests in the same session left behind."""
    yield
    with engine.begin() as conn:
        for table in reversed(SQLModel.metadata.sorted_tables):
            conn.execute(table.delete())
