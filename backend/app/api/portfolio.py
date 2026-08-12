from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlmodel import select

from app.db import get_session
from app.models import Trade
from app.timeutil import as_utc, to_epoch

router = APIRouter()

# Trailing windows rather than calendar day/week/month — sidesteps having to
# pick a timezone to define "today" in (the DB stores UTC; the user isn't).
_PERIOD_WINDOWS: dict[str, timedelta] = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
}


@router.get("/api/portfolio/stats")
async def portfolio_stats(period: str = Query("all", pattern="^(all|day|week|month)$")):
    with get_session() as session:
        closed = session.exec(select(Trade).where(Trade.status == "CLOSED").order_by(Trade.exit_time)).all()

    window = _PERIOD_WINDOWS.get(period)
    if window is not None:
        cutoff = datetime.now(timezone.utc) - window
        closed = [t for t in closed if t.exit_time is not None and as_utc(t.exit_time) >= cutoff]

    total_trades = len(closed)
    wins = [t for t in closed if (t.pnl or 0) > 0]
    losses = [t for t in closed if (t.pnl or 0) <= 0]
    total_pnl = sum(t.pnl or 0 for t in closed)
    win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0

    equity_curve = []
    cumulative = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for t in closed:
        cumulative += t.pnl or 0
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
        equity_curve.append({"time": to_epoch(t.exit_time), "equity": round(cumulative, 2)})

    return {
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "max_drawdown": round(max_drawdown, 2),
        "equity_curve": equity_curve,
    }
