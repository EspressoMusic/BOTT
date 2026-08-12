import pandas as pd

from app.strategies.atr_trend_following import AtrTrendFollowingStrategy


def _closes_down_then_up() -> list[float]:
    down = [110 - i * 0.5 for i in range(30)]
    up = [down[-1] + i * 1.5 for i in range(30)]
    return down + up


def _make_df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes, "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes]})


def _run(strategy: AtrTrendFollowingStrategy, closes: list[float]) -> list:
    results = []
    for i in range(strategy.required_history(), len(closes) + 1):
        df = _make_df(closes[:i])
        results.append(strategy.evaluate(df))
    return results


def test_required_history():
    strategy = AtrTrendFollowingStrategy(trend_period=20, atr_period=14)
    assert strategy.required_history() == 25


def test_detects_bullish_trend_cross_with_atr_stops():
    strategy = AtrTrendFollowingStrategy()
    results = _run(strategy, _closes_down_then_up())
    actions = [r.signal.action for r in results]

    assert actions.count("BUY") >= 1
    assert actions.count("SELL") == 0

    buy_result = next(r for r in results if r.signal.action == "BUY")
    assert buy_result.signal.stop_loss is not None
    assert buy_result.signal.take_profit is not None
    assert buy_result.signal.stop_loss < buy_result.signal.take_profit


def test_indicators_reported():
    strategy = AtrTrendFollowingStrategy()
    df = _make_df(_closes_down_then_up())
    result = strategy.evaluate(df)
    assert set(result.indicators) == {"price", "sma_trend", "atr"}
    assert result.indicators["atr"] >= 0
