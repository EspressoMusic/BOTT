import pandas as pd

from app.strategies.moving_average import MovingAverageCrossoverStrategy


def _prices_downtrend_then_uptrend() -> list[float]:
    down = [110 - i * 0.5 for i in range(30)]  # 110 -> 95.5
    up = [95.5 + i * 1.5 for i in range(30)]  # 95.5 -> 139
    return down + up


def test_required_history_matches_slow_plus_buffer():
    strategy = MovingAverageCrossoverStrategy(fast=9, slow=21)
    assert strategy.required_history() == 26


def test_detects_single_bullish_crossover_during_reversal():
    strategy = MovingAverageCrossoverStrategy(fast=9, slow=21)
    prices = _prices_downtrend_then_uptrend()

    # Feed the strategy incrementally, exactly like StrategyEngine does one closed
    # candle at a time, and record every signal produced along the way.
    actions = []
    for i in range(strategy.required_history(), len(prices) + 1):
        df = pd.DataFrame({"close": prices[:i]})
        result = strategy.evaluate(df)
        actions.append(result.signal.action)

    assert actions.count("BUY") == 1
    assert actions.count("SELL") == 0
    assert actions[-1] == "NONE"


def test_thought_and_indicators_after_established_uptrend():
    strategy = MovingAverageCrossoverStrategy(fast=9, slow=21)
    df = pd.DataFrame({"close": _prices_downtrend_then_uptrend()})

    result = strategy.evaluate(df)

    assert "עולה" in result.thought
    assert result.indicators["ema_fast"] > result.indicators["ema_slow"]
    assert result.signal.action == "NONE"  # already crossed earlier, no fresh signal


def test_detects_bearish_crossover_on_reversal_down():
    strategy = MovingAverageCrossoverStrategy(fast=9, slow=21)
    up = [90 + i * 0.5 for i in range(30)]  # 90 -> 104.5
    down = [104.5 - i * 1.5 for i in range(30)]  # 104.5 -> 60
    prices = up + down

    actions = []
    for i in range(strategy.required_history(), len(prices) + 1):
        df = pd.DataFrame({"close": prices[:i]})
        result = strategy.evaluate(df)
        actions.append(result.signal.action)

    assert actions.count("SELL") == 1
    assert actions.count("BUY") == 0
