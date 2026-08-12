import json
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app.broker.base import Candle
from app.broker.simulated import SimulatedBrokerAdapter
from app.db import get_session
from app.models import FeedbackRule, Trade
from app.order_service import OrderService
from app.settings_store import set_setting
from app.strategies.base import Signal
from app.ws.manager import ConnectionManager

INSTRUMENT = "XAU_USD"


def _service() -> OrderService:
    return OrderService(SimulatedBrokerAdapter(), ConnectionManager(), INSTRUMENT, granularity="M1")


def _candle(close: float, low: float | None = None, high: float | None = None) -> Candle:
    return Candle(
        time=datetime.now(timezone.utc),
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
    )


@pytest.mark.asyncio
async def test_handle_signal_opens_a_trade():
    service = _service()
    service._broker.update_price(2400.0)  # seed a price so the sim broker can fill

    await service.handle_signal(
        Signal(action="BUY", reason="test buy", stop_loss=2390.0, take_profit=2420.0),
        strategy_id="ma_crossover",
        candle=_candle(2400.0),
        indicators={},
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1
    assert trades[0].status == "OPEN"
    assert trades[0].side == "BUY"
    assert trades[0].entry_price == 2400.0


@pytest.mark.asyncio
async def test_handle_signal_ignored_when_bot_disabled():
    set_setting("bot_enabled", "false")
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=None, take_profit=None),
        strategy_id="ma_crossover",
        candle=_candle(2400.0),
        indicators={},
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert trades == []
    set_setting("bot_enabled", "true")  # restore default for other tests


@pytest.mark.asyncio
async def test_handle_signal_respects_max_concurrent_positions():
    set_setting("max_concurrent_positions", "1")
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(Signal(action="BUY", reason="first"), "ma_crossover", _candle(2400.0), {})
    await service.handle_signal(Signal(action="BUY", reason="second"), "ma_crossover", _candle(2400.0), {})

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1
    assert trades[0].signal_reason == "first"


@pytest.mark.asyncio
async def test_handle_signal_blocked_by_active_feedback_rule():
    with get_session() as session:
        session.add(
            FeedbackRule(
                description="block buy when rsi high",
                conditions_json=json.dumps({"left": "rsi", "op": ">", "right": 80}),
                action="block_entry",
                side_filter="BUY",
                is_active=True,
            )
        )
        session.commit()

    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(Signal(action="BUY", reason="test"), "ma_crossover", _candle(2400.0), {"rsi": 85})

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert trades == []


@pytest.mark.asyncio
async def test_signal_without_sl_tp_gets_default_protective_stops():
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="BUY", reason="no explicit sl/tp"), "ma_crossover", _candle(2400.0), {}
    )

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.stop_loss == 2400.0 - service._default_stop_distance
    assert trade.take_profit == 2400.0 + service._default_target_distance


@pytest.mark.asyncio
async def test_stop_loss_hit_closes_trade_with_correct_pnl():
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2420.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )

    closing_candle = _candle(close=2390.0, low=2388.0, high=2396.0)
    await service.on_candle_closed("M1", closing_candle)

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1
    assert trades[0].status == "CLOSED"
    assert trades[0].exit_reason == "SL"
    assert trades[0].pnl == pytest.approx((2390.0 - 2400.0) * trades[0].units)


@pytest.mark.asyncio
async def test_on_candle_closed_ignores_other_granularities():
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2420.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )

    # An M5 candle whose range would hit the SL should NOT close the trade —
    # OrderService only watches the finest (M1) granularity.
    wide_candle = _candle(close=2400.0, low=2350.0, high=2450.0)
    await service.on_candle_closed("M5", wide_candle)

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert trades[0].status == "OPEN"
