"""Small shared trade-stats helpers that need to stay consistent across call
sites — the daily-profit auto-stop (order_service) and the header's "today's
P&L" display both need the exact same "today" boundary and the same sum, or
the header could show a profit the auto-stop doesn't agree with.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import select

from app.db import get_session
from app.models import Trade
from app.timeutil import as_utc, trading_day_start_utc


def todays_realized_pnl() -> float:
    """Sum of closed trades' pnl since the current trading day started (the
    last London session open, 08:00 UTC — see timeutil.trading_day_start_utc).
    Realized only, same basis as the portfolio stats page — floating pnl on
    still-open positions doesn't count until the trade actually closes.

    The day boundary is computed relative to the most recent trade's own
    exit_time rather than true wall-clock UTC. Reason: MT5's candle/trade
    timestamps are labeled UTC but are actually the broker server's local
    clock (see scripts/session_performance.py's BROKER_UTC_OFFSET_HOURS —
    a measured, DST-dependent few-hour skew). Comparing that clock against
    real `datetime.now(timezone.utc)` shifts the "today" boundary by the
    same skew, silently pulling yesterday's trades into (or dropping this
    morning's trades out of) today's total. Anchoring on the data's own
    clock instead keeps both sides of the comparison consistent regardless
    of which broker (or offset) is active — for data sources with no skew
    (OANDA/Yahoo/simulated) this is just "now" with a few minutes of lag.
    """
    with get_session() as session:
        closed = session.exec(select(Trade).where(Trade.status == "CLOSED")).all()
    exit_times = [as_utc(t.exit_time) for t in closed if t.exit_time is not None]
    reference_now = max(exit_times) if exit_times else datetime.now(timezone.utc)
    day_start = trading_day_start_utc(reference_now)
    return sum(t.pnl or 0 for t in closed if t.exit_time is not None and as_utc(t.exit_time) >= day_start)
