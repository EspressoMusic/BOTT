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

from datetime import datetime, timedelta, timezone


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def to_epoch(dt: datetime) -> int:
    return int(as_utc(dt).timestamp())


# London session open per scripts/session_performance.py's SESSIONS table
# (08:00-17:00 UTC, fixed — not DST-adjusted).
TRADING_DAY_RESET_HOUR_UTC = 8


def trading_day_start_utc(now_utc: datetime | None = None) -> datetime:
    """Start of the current "trading day" — the most recent London session
    open (08:00 UTC). Before that hour, `now` still belongs to the previous
    trading day. Used to reset the daily-profit auto-stop at session open
    rather than at UTC/local midnight."""
    now_utc = now_utc or datetime.now(timezone.utc)
    boundary = now_utc.replace(hour=TRADING_DAY_RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if now_utc < boundary:
        boundary -= timedelta(days=1)
    return boundary


def trading_day_str(now_utc: datetime | None = None) -> str:
    return trading_day_start_utc(now_utc).date().isoformat()
