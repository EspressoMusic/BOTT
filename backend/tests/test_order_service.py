import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from app.broker.base import Candle
from app.broker.simulated import SimulatedBrokerAdapter
from app.db import get_session
from app.models import FeedbackRule, Trade
from app.order_service import OrderService
from app.settings_store import get_setting, is_bot_enabled, set_setting
from app.strategies.base import Signal
from app.timeutil import trading_day_str
from app.ws.manager import ConnectionManager

INSTRUMENT = "XAU_USD"


def _service(trade_cooldown_minutes: float = 0.0) -> OrderService:
    # Default 0 (disabled) so every pre-existing test — none of which were
    # written with a post-close cooldown in mind — keeps behaving exactly as
    # before; the cooldown-specific tests below opt into a real value.
    return OrderService(
        SimulatedBrokerAdapter(),
        ConnectionManager(),
        INSTRUMENT,
        granularity="M1",
        trade_cooldown_minutes=trade_cooldown_minutes,
    )


def _candle(
    close: float, low: float | None = None, high: float | None = None, time: datetime | None = None
) -> Candle:
    return Candle(
        time=time if time is not None else datetime.now(timezone.utc),
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
async def test_position_size_defaults_to_flat_risk_units():
    # risk_pct defaults to "0" (disabled) — units must come straight from
    # risk_units, unaffected by account balance or stop distance.
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2420.0),
        strategy_id="ma_crossover",
        candle=_candle(2400.0),
        indicators={},
    )

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.units == float(get_setting("risk_units"))


@pytest.mark.asyncio
async def test_position_size_scales_with_risk_pct_and_stop_distance():
    # 100k sim balance, risk_pct=0.25 -> risk $250 per trade. Stop distance
    # here is 10 (2400 - 2390), so units must be 250 / 10 = 25 — losing
    # exactly $250 (0.25% of balance) if the stop is hit, regardless of what
    # risk_units is set to.
    set_setting("risk_pct", "0.25")
    set_setting("risk_units", "999")  # must be ignored while risk_pct is active
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2420.0),
        strategy_id="ma_crossover",
        candle=_candle(2400.0),
        indicators={},
    )

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.units == pytest.approx(25.0)

    set_setting("risk_pct", "0")
    set_setting("risk_units", "10")


@pytest.mark.asyncio
async def test_position_size_uses_fixed_risk_dollars_over_pct_and_units():
    # risk_dollars=50 must win over both risk_pct and risk_units when all
    # three are set — stop distance is 10 (2400 - 2390), so units = 50/10 = 5,
    # losing exactly $50 if the stop is hit regardless of account balance.
    set_setting("risk_dollars", "50")
    set_setting("risk_pct", "0.25")  # must be ignored while risk_dollars is active
    set_setting("risk_units", "999")  # must be ignored while risk_dollars is active
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2420.0),
        strategy_id="ma_crossover",
        candle=_candle(2400.0),
        indicators={},
    )

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.units == pytest.approx(5.0)

    set_setting("risk_dollars", "0")
    set_setting("risk_pct", "0")
    set_setting("risk_units", "10")


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


@pytest.mark.asyncio
async def test_breakeven_extension_moves_stop_and_extends_target_when_tp_reached():
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )

    # High reaches the original TP (2410) but low stays above the new
    # breakeven stop (2400), so the extension can be observed without an
    # immediate stop-out on the very same bar.
    touching_candle = _candle(close=2408.0, low=2405.0, high=2410.0)
    await service.on_candle_closed("M1", touching_candle)

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.status == "OPEN"
    assert trade.stop_loss == pytest.approx(2400.0)  # breakeven = entry
    assert trade.take_profit == pytest.approx(2400.0 + 4.0 * 10.0)  # entry + 4x original risk


@pytest.mark.asyncio
async def test_breakeven_extension_does_not_retrigger_once_applied():
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    await service.on_candle_closed("M1", _candle(close=2408.0, low=2405.0, high=2410.0))

    with get_session() as session:
        extended_tp = session.exec(select(Trade)).first().take_profit

    # A later candle reaching further into the (already extended) target
    # range shouldn't push it out again.
    await service.on_candle_closed("M1", _candle(close=2415.0, low=2412.0, high=2420.0))

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.take_profit == extended_tp


@pytest.mark.asyncio
async def test_breakeven_extension_defers_to_original_sl_when_same_candle_hits_both():
    # A single wide candle whose range covers BOTH the original stop (2390)
    # and the original target (2410) — ambiguous which came first intrabar,
    # so this should close as a normal SL loss rather than extend past a
    # stop it may well have already hit.
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    wide_candle = _candle(close=2400.0, low=2388.0, high=2412.0)
    await service.on_candle_closed("M1", wide_candle)

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.status == "CLOSED"
    assert trade.exit_reason == "SL"
    assert trade.stop_loss == 2390.0  # never got moved to breakeven


@pytest.mark.asyncio
async def test_breakeven_extension_does_nothing_before_original_tp_reached():
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    # Below halfway (2405) too, so neither rule fires.
    await service.on_candle_closed("M1", _candle(close=2402.0, low=2400.5, high=2403.0))

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.stop_loss == 2390.0
    assert trade.take_profit == 2410.0


@pytest.mark.asyncio
async def test_halfway_breakeven_moves_stop_to_entry_without_extending_target():
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    # Halfway to target = 2405; stays well clear of the original stop (2390)
    # and of the original target (2410), so only the halfway rule should fire.
    await service.on_candle_closed("M1", _candle(close=2406.0, low=2403.0, high=2406.0))

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.status == "OPEN"
    assert trade.stop_loss == pytest.approx(2400.0)  # moved to breakeven
    assert trade.take_profit == pytest.approx(2410.0)  # target untouched


@pytest.mark.asyncio
async def test_halfway_breakeven_works_for_sell_side_too():
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="SELL", reason="test", stop_loss=2410.0, take_profit=2390.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    # Halfway to target = 2395.
    await service.on_candle_closed("M1", _candle(close=2394.0, low=2394.0, high=2397.0))

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.status == "OPEN"
    assert trade.stop_loss == pytest.approx(2400.0)
    assert trade.take_profit == pytest.approx(2390.0)


@pytest.mark.asyncio
async def test_halfway_breakeven_defers_to_original_sl_when_same_candle_hits_both():
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    # Same candle's range covers both the original stop (2390) and halfway (2405) —
    # ambiguous which came first, so this should close as a normal SL loss instead
    # of "rescuing" the trade to breakeven.
    wide_candle = _candle(close=2400.0, low=2388.0, high=2406.0)
    await service.on_candle_closed("M1", wide_candle)

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.status == "CLOSED"
    assert trade.exit_reason == "SL"
    assert trade.stop_loss == 2390.0  # never got moved to breakeven


@pytest.mark.asyncio
async def test_full_extension_still_applies_after_halfway_already_moved_stop():
    # Regression test: once the halfway rule has already moved the stop to
    # entry, abs(entry - stop_loss) reads as ~0 — the full extension must
    # still size the new target off the ORIGINAL risk (captured in
    # initial_risk), not off that now-collapsed distance.
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    # First candle: reaches halfway (2405) only.
    await service.on_candle_closed("M1", _candle(close=2406.0, low=2403.0, high=2406.0))
    with get_session() as session:
        mid_trade = session.exec(select(Trade)).first()
    assert mid_trade.stop_loss == pytest.approx(2400.0)
    assert mid_trade.take_profit == pytest.approx(2410.0)

    # Second candle: reaches the full original target (2410).
    await service.on_candle_closed("M1", _candle(close=2412.0, low=2408.0, high=2412.0))
    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.status == "OPEN"
    assert trade.stop_loss == pytest.approx(2400.0)
    assert trade.take_profit == pytest.approx(2400.0 + 4.0 * 10.0)  # sized off the original 10-point risk


@pytest.mark.asyncio
async def test_breakeven_extension_works_for_sell_side_too():
    service = _service()
    service._broker.update_price(2400.0)
    await service.handle_signal(
        Signal(action="SELL", reason="test", stop_loss=2410.0, take_profit=2390.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )

    touching_candle = _candle(close=2392.0, low=2390.0, high=2395.0)
    await service.on_candle_closed("M1", touching_candle)

    with get_session() as session:
        trade = session.exec(select(Trade)).first()
    assert trade.status == "OPEN"
    assert trade.stop_loss == pytest.approx(2400.0)
    assert trade.take_profit == pytest.approx(2400.0 - 4.0 * 10.0)


@pytest.mark.asyncio
async def test_chat_direction_bias_blocks_opposite_side():
    set_setting("chat_direction_bias", "BUY")
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(Signal(action="SELL", reason="test"), "ma_crossover", _candle(2400.0), {})

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert trades == []
    set_setting("chat_direction_bias", "")


@pytest.mark.asyncio
async def test_chat_direction_bias_allows_matching_side_and_then_clears():
    set_setting("chat_direction_bias", "BUY")
    set_setting("max_concurrent_positions", "2")
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(Signal(action="BUY", reason="test"), "ma_crossover", _candle(2400.0), {})

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1
    assert get_setting("chat_direction_bias") == ""

    # Bias cleared — a SELL signal should now go through normally.
    await service.handle_signal(Signal(action="SELL", reason="test 2"), "ma_crossover", _candle(2400.0), {})
    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 2
    set_setting("max_concurrent_positions", "1")


@pytest.mark.asyncio
async def test_ema50_trend_filter_blocks_sell_above_ema50():
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="SELL", reason="test"), "ma_crossover", _candle(2400.0), {"ema50": 2380.0}
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert trades == []


@pytest.mark.asyncio
async def test_ema50_trend_filter_allows_buy_above_ema50():
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="BUY", reason="test"), "ma_crossover", _candle(2400.0), {"ema50": 2380.0}
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1


@pytest.mark.asyncio
async def test_ema50_trend_filter_blocks_buy_below_ema50():
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="BUY", reason="test"), "ma_crossover", _candle(2400.0), {"ema50": 2420.0}
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert trades == []


@pytest.mark.asyncio
async def test_ema50_trend_filter_allows_sell_below_ema50():
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="SELL", reason="test"), "ma_crossover", _candle(2400.0), {"ema50": 2420.0}
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1


@pytest.mark.asyncio
async def test_ema50_trend_filter_does_nothing_when_ema50_missing():
    # Backward compatible with any strategy/indicators dict that doesn't
    # report ema50 (shouldn't happen in practice now that strategy_engine
    # always adds it, but handle_signal must not require it).
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(Signal(action="SELL", reason="test"), "ma_crossover", _candle(2400.0), {})

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1


@pytest.mark.asyncio
async def test_daily_profit_target_disables_bot_once_reached():
    set_setting("daily_profit_target_pct", "1")  # 1% of the 100k sim starting balance
    set_setting("risk_units", "1000")
    service = _service()
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2450.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    with get_session() as session:
        trade_id = session.exec(select(Trade)).first().id

    # Manual close at a price netting 1% of the 100k starting balance —
    # (2401 - 2400) * 1000 units = 1000 pnl. Closing manually (rather than
    # via a candle reaching take_profit) keeps this test about the daily
    # target itself, independent of the breakeven/target-extension logic
    # that now runs before any TP-hit close.
    service._broker.update_price(2401.0)
    await service.close_position_manually(trade_id)

    assert is_bot_enabled() is False
    assert get_setting("daily_stop_date") == trading_day_str()
    assert get_setting("auto_stop_message")  # persisted so a reload still explains why

    set_setting("daily_profit_target_pct", "0")
    set_setting("risk_units", "10")
    set_setting("bot_enabled", "true")
    set_setting("daily_stop_date", "")
    set_setting("auto_stop_message", "")


@pytest.mark.asyncio
async def test_daily_profit_target_disabled_by_default():
    service = _service()  # daily_profit_target_pct defaults to "0" — disabled
    service._broker.update_price(2400.0)

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2401.0),
        "ma_crossover",
        _candle(2400.0),
        {},
    )
    await service.on_candle_closed("M1", _candle(close=2401.0, low=2399.0, high=2402.0))

    assert is_bot_enabled() is True


@pytest.mark.asyncio
async def test_trade_cooldown_blocks_a_new_signal_right_after_a_close():
    service = _service(trade_cooldown_minutes=15.0)
    service._broker.update_price(2400.0)
    t0 = datetime.now(timezone.utc)

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0, time=t0),
        {},
    )
    # SL hit — trade closes at t0 + 1 minute.
    await service.on_candle_closed(
        "M1", _candle(close=2390.0, low=2388.0, high=2392.0, time=t0 + timedelta(minutes=1))
    )

    # Only 5 minutes later — still inside the 15-minute cooldown.
    await service.handle_signal(
        Signal(action="BUY", reason="test 2"),
        "ma_crossover",
        _candle(2400.0, time=t0 + timedelta(minutes=6)),
        {},
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1
    assert trades[0].status == "CLOSED"


@pytest.mark.asyncio
async def test_trade_cooldown_allows_a_new_signal_once_it_elapses():
    service = _service(trade_cooldown_minutes=15.0)
    service._broker.update_price(2400.0)
    t0 = datetime.now(timezone.utc)

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0, time=t0),
        {},
    )
    await service.on_candle_closed(
        "M1", _candle(close=2390.0, low=2388.0, high=2392.0, time=t0 + timedelta(minutes=1))
    )

    # 16 minutes after the close — cooldown has elapsed.
    await service.handle_signal(
        Signal(action="BUY", reason="test 2"),
        "ma_crossover",
        _candle(2400.0, time=t0 + timedelta(minutes=17)),
        {},
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 2
    assert trades[1].status == "OPEN"


@pytest.mark.asyncio
async def test_trade_cooldown_disabled_when_zero():
    service = _service(trade_cooldown_minutes=0.0)
    service._broker.update_price(2400.0)
    t0 = datetime.now(timezone.utc)

    await service.handle_signal(
        Signal(action="BUY", reason="test", stop_loss=2390.0, take_profit=2410.0),
        "ma_crossover",
        _candle(2400.0, time=t0),
        {},
    )
    await service.on_candle_closed(
        "M1", _candle(close=2390.0, low=2388.0, high=2392.0, time=t0 + timedelta(minutes=1))
    )
    # Immediately after — no cooldown configured, so this should open.
    await service.handle_signal(
        Signal(action="BUY", reason="test 2"),
        "ma_crossover",
        _candle(2400.0, time=t0 + timedelta(minutes=1, seconds=1)),
        {},
    )

    with get_session() as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 2
    assert trades[1].status == "OPEN"
