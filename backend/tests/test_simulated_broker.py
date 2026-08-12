import pytest

from app.broker.simulated import SimulatedBrokerAdapter


@pytest.mark.asyncio
async def test_place_order_fills_at_last_price():
    broker = SimulatedBrokerAdapter()
    broker.update_price(2400.0)

    result = await broker.place_order("XAU_USD", "BUY", 10, stop_loss=2390.0, take_profit=2420.0)

    assert result.success is True
    assert result.fill_price == 2400.0
    trades = await broker.get_open_trades()
    assert len(trades) == 1
    assert trades[0].side == "BUY"


@pytest.mark.asyncio
async def test_place_order_fails_without_a_price():
    broker = SimulatedBrokerAdapter()
    result = await broker.place_order("XAU_USD", "BUY", 10)
    assert result.success is False


@pytest.mark.asyncio
async def test_stop_loss_triggers_within_candle_range():
    broker = SimulatedBrokerAdapter()
    broker.update_price(2400.0)
    await broker.place_order("XAU_USD", "BUY", 10, stop_loss=2390.0, take_profit=2420.0)

    triggered = broker.check_stop_loss_take_profit(low=2385.0, high=2405.0)

    assert len(triggered) == 1
    pos, exit_price, reason = triggered[0]
    assert reason == "SL"
    assert exit_price == 2390.0
    assert (await broker.get_open_trades()) == []


@pytest.mark.asyncio
async def test_take_profit_triggers_within_candle_range():
    broker = SimulatedBrokerAdapter()
    broker.update_price(2400.0)
    await broker.place_order("XAU_USD", "SELL", 10, stop_loss=2420.0, take_profit=2380.0)

    triggered = broker.check_stop_loss_take_profit(low=2375.0, high=2395.0)

    assert len(triggered) == 1
    pos, exit_price, reason = triggered[0]
    assert reason == "TP"
    assert exit_price == 2380.0


@pytest.mark.asyncio
async def test_pnl_computed_correctly_for_buy_and_sell():
    broker = SimulatedBrokerAdapter(starting_balance=100_000.0)
    broker.update_price(2400.0)
    await broker.place_order("XAU_USD", "BUY", 10, stop_loss=2390.0, take_profit=2420.0)

    broker.check_stop_loss_take_profit(low=2415.0, high=2425.0)  # hits TP at 2420

    state = await broker.get_account_state()
    assert state.balance == pytest.approx(100_000.0 + (2420.0 - 2400.0) * 10)


@pytest.mark.asyncio
async def test_manual_close_position():
    broker = SimulatedBrokerAdapter()
    broker.update_price(2400.0)
    result = await broker.place_order("XAU_USD", "BUY", 10)
    broker.update_price(2410.0)

    close_result = await broker.close_position(result.broker_trade_id)

    assert close_result.success is True
    assert close_result.fill_price == 2410.0
    assert (await broker.get_open_trades()) == []
