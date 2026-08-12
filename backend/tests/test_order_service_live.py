"""OrderService's live-mode path (live=True): real brokers manage SL/TP
server-side, so closes are detected by reconciling DB OPEN trades against
the broker's actual open positions instead of scanning candle ranges against
an in-process position book. FakeLiveBroker below stands in for a real
BrokerAdapter (OANDA/MT5) — only the methods OrderService actually calls in
live mode.
"""

from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app.broker.base import AccountState, BrokerTrade, Candle, OrderResult
from app.db import get_session
from app.models import Trade
from app.order_service import OrderService
from app.strategies.base import Signal
from app.ws.manager import ConnectionManager

INSTRUMENT = "XAU_USD"


class FakeLiveBroker:
    def __init__(self):
        self.open_ids: set[str] = set()
        self._next_id = 1

    async def place_order(self, instrument, side, units, stop_loss=None, take_profit=None) -> OrderResult:
        trade_id = str(self._next_id)
        self._next_id += 1
        self.open_ids.add(trade_id)
        return OrderResult(success=True, broker_trade_id=trade_id, fill_price=2400.0, message="filled")

    async def close_position(self, trade_id: str) -> OrderResult:
        self.open_ids.discard(trade_id)
        return OrderResult(success=True, broker_trade_id=trade_id, fill_price=2400.0, message="closed")

    async def get_open_trades(self) -> list[BrokerTrade]:
        return [
            BrokerTrade(
                broker_trade_id=tid,
                instrument=INSTRUMENT,
                side="BUY",
                units=10,
                entry_price=2400.0,
                unrealized_pnl=0.0,
                stop_loss=None,
                take_profit=None,
            )
            for tid in self.open_ids
        ]

    async def get_account_state(self) -> AccountState:
        return AccountState(balance=1000.0, unrealized_pnl=0.0, margin_available=1000.0, open_trade_count=len(self.open_ids))


def _candle(close: float, low: float | None = None, high: float | None = None) -> Candle:
    return Candle(
        time=datetime.now(timezone.utc),
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
    )


def _live_service() -> tuple[OrderService, FakeLiveBroker]:
    broker = FakeLiveBroker()
    service = OrderService(broker, ConnectionManager(), INSTRUMENT, granularity="M1", live=True)
    return service, broker


@pytest.mark.asyncio
async def test_live_signal_opens_a_trade_via_real_broker():
    service, broker = _live_service()

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2420.0),
        strategy_id="ma_crossover",
        candle=_candle(2400.0),
        indicators={},
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1
    assert trades[0].status == "OPEN"
    assert trades[0].broker_trade_id in broker.open_ids


@pytest.mark.asyncio
async def test_live_reconcile_infers_stop_loss_hit_when_broker_position_disappears():
    service, broker = _live_service()
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2420.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    # Simulate the broker having closed the position server-side (SL hit) —
    # it no longer shows up in get_open_trades().
    broker.open_ids.clear()

    closing_candle = _candle(close=2390.0, low=2388.0, high=2396.0)
    await service.on_candle_closed("M1", closing_candle)

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1
    assert trades[0].status == "CLOSED"
    assert trades[0].exit_reason == "SL"
    assert trades[0].exit_price == 2390.0


@pytest.mark.asyncio
async def test_live_reconcile_falls_back_to_manual_when_no_level_crossed():
    service, broker = _live_service()
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2420.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    broker.open_ids.clear()  # closed at the broker, but price never reached SL or TP

    closing_candle = _candle(close=2405.0, low=2402.0, high=2408.0)
    await service.on_candle_closed("M1", closing_candle)

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert trades[0].status == "CLOSED"
    assert trades[0].exit_reason == "MANUAL"
    assert trades[0].exit_price == 2405.0


@pytest.mark.asyncio
async def test_live_reconcile_leaves_trade_open_when_still_open_at_broker():
    service, broker = _live_service()
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2420.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )

    # Still open at the broker — even though this candle's range would have
    # hit the SL for a simulated position, the broker is the source of truth.
    wide_candle = _candle(close=2400.0, low=2380.0, high=2420.0)
    await service.on_candle_closed("M1", wide_candle)

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert trades[0].status == "OPEN"
