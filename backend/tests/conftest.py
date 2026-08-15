"""Points the test suite at an isolated SQLite file so tests never touch the
live dev server's bott.db (which may be running concurrently). Must set the env
var before any `app.db` import happens — conftest.py is always collected first.
"""

import os
from pathlib import Path

TEST_DB_PATH = Path(__file__).parent / "test_bott.db"
os.environ["BOTT_DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

# Tests place plenty of fake trades (fake prices, "test" as the strategy id,
# instrument defaulting to XAU_USD) — without this, a real TELEGRAM_BOT_TOKEN
# in .env means every test run spams the real Telegram chat with dozens of
# fake "trade opened/closed" messages. Env vars take precedence over .env in
# pydantic-settings, and this must run before app.config is first imported
# anywhere (conftest.py is always collected first) for that to take effect.
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_CHAT_ID"] = ""

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
