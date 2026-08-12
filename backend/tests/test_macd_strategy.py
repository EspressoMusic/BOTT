import pandas as pd

from app.strategies.macd_trend import MacdTrendStrategy


def _downtrend_then_uptrend() -> list[float]:
    down = [200 - i * 1.0 for i in range(50)]
    up = [down[-1] + i * 1.5 for i in range(40)]
    return down + up


def _run(strategy: MacdTrendStrategy, prices: list[float]) -> list[str]:
    actions = []
    for i in range(strategy.required_history(), len(prices) + 1):
        df = pd.DataFrame({"close": prices[:i]})
        result = strategy.evaluate(df)
        actions.append(result.signal.action)
    return actions


def test_required_history():
    strategy = MacdTrendStrategy(fast=12, slow=26, signal_period=9)
    assert strategy.required_history() == 26 + 9 + 5


def test_detects_bullish_macd_crossover_during_reversal():
    strategy = MacdTrendStrategy()
    actions = _run(strategy, _downtrend_then_uptrend())
    assert actions.count("BUY") >= 1
    assert actions.count("SELL") == 0


def test_indicators_reported():
    strategy = MacdTrendStrategy()
    df = pd.DataFrame({"close": _downtrend_then_uptrend()})
    result = strategy.evaluate(df)
    assert set(result.indicators) == {"price", "macd", "macd_signal", "macd_hist"}
