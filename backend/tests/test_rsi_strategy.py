import pandas as pd

from app.strategies.rsi_mean_reversion import RsiMeanReversionStrategy


def _decline_then_bounce() -> list[float]:
    down = [200 - i * 2 for i in range(40)]  # steady decline -> pushes RSI low
    up = [down[-1] + i * 3 for i in range(15)]  # sharp bounce -> RSI climbs back out
    return down + up


def _rally_then_drop() -> list[float]:
    up = [100 + i * 2 for i in range(40)]  # steady rally -> pushes RSI high
    down = [up[-1] - i * 3 for i in range(15)]  # sharp drop -> RSI falls back out
    return up + down


def _run(strategy: RsiMeanReversionStrategy, prices: list[float]) -> list[str]:
    actions = []
    for i in range(strategy.required_history(), len(prices) + 1):
        df = pd.DataFrame({"close": prices[:i]})
        result = strategy.evaluate(df)
        actions.append(result.signal.action)
    return actions


def test_required_history_matches_period_plus_buffer():
    strategy = RsiMeanReversionStrategy(period=14)
    assert strategy.required_history() == 19


def test_detects_bullish_exit_from_oversold():
    strategy = RsiMeanReversionStrategy()
    actions = _run(strategy, _decline_then_bounce())
    assert actions.count("BUY") >= 1
    assert actions.count("SELL") == 0


def test_detects_bearish_exit_from_overbought():
    strategy = RsiMeanReversionStrategy()
    actions = _run(strategy, _rally_then_drop())
    assert actions.count("SELL") >= 1
    assert actions.count("BUY") == 0


def test_rsi_indicator_is_bounded_0_to_100():
    strategy = RsiMeanReversionStrategy()
    df = pd.DataFrame({"close": _decline_then_bounce()})
    result = strategy.evaluate(df)
    assert 0.0 <= result.indicators["rsi"] <= 100.0
