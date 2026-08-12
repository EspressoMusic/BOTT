"""SQLite has no native timezone type, so SQLAlchemy round-trips every
`datetime` column as naive — even though every datetime this app ever writes
(via `datetime.now(timezone.utc)` or a UTC-aware broker/candle time) is UTC.
A naive datetime's own `.timestamp()` assumes the *local* system clock, so on
any machine not set to UTC (e.g. Asia/Jerusalem, UTC+2/+3), converting a
DB-reloaded datetime straight to epoch silently shifts it by the local UTC
offset. Use this instead of calling `.timestamp()` directly on any datetime
that came back from the database.
"""

from __future__ import annotations

from datetime import datetime, timezone


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def to_epoch(dt: datetime) -> int:
    return int(as_utc(dt).timestamp())
