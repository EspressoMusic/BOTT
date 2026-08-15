from datetime import datetime, timedelta

from sqlmodel import select

from app.db import get_session
from app.models import Trade
from app.timeutil import trading_day_start_utc
from app.trade_stats import todays_realized_pnl

INSTRUMENT = "XAU_USD"


def _closed_trade(pnl: float, exit_time: datetime) -> Trade:
    return Trade(
        instrument=INSTRUMENT,
        side="BUY",
        status="CLOSED",
        entry_price=2400.0,
        entry_time=exit_time - timedelta(minutes=5),
        exit_price=2400.0 + pnl,
        exit_time=exit_time,
        exit_reason="TP",
        units=1,
        pnl=pnl,
        strategy_id="scalping",
    )


def test_todays_realized_pnl_sums_only_trades_since_trading_day_start():
    day_start = trading_day_start_utc()
    with get_session() as session:
        session.add(_closed_trade(10.0, day_start + timedelta(minutes=5)))
        session.add(_closed_trade(5.0, day_start + timedelta(hours=2)))
        session.add(_closed_trade(-100.0, day_start - timedelta(minutes=1)))  # previous trading day
        session.commit()

    assert todays_realized_pnl() == 15.0


def test_todays_realized_pnl_is_zero_with_no_closed_trades():
    assert todays_realized_pnl() == 0


def test_todays_realized_pnl_ignores_open_trades():
    day_start = trading_day_start_utc()
    with get_session() as session:
        trade = _closed_trade(20.0, day_start + timedelta(minutes=1))
        trade.status = "OPEN"
        trade.exit_price = None
        trade.exit_time = None
        trade.exit_reason = None
        trade.pnl = None
        session.add(trade)
        session.commit()

    with get_session() as session:
        assert len(session.exec(select(Trade)).all()) == 1
    assert todays_realized_pnl() == 0
