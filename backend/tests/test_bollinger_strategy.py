import pandas as pd

from app.strategies.bollinger_breakout import BollingerBreakoutStrategy


def _tight_range_then_breakout_up() -> list[float]:
    flat = [100 + (0.3 if i % 2 == 0 else -0.3) for i in range(30)]  # tight range -> narrow bands
    breakout = [100 + i * 3 for i in range(1, 10)]  # sharp move beyond the upper band
    return flat + breakout


def _tight_range_then_breakdown() -> list[float]:
    flat = [100 + (0.3 if i % 2 == 0 else -0.3) for i in range(30)]
    breakdown = [100 - i * 3 for i in range(1, 10)]
    return flat + breakdown


def _run(strategy: BollingerBreakoutStrategy, prices: list[float]) -> list[str]:
    actions = []
    for i in range(strategy.required_history(), len(prices) + 1):
        df = pd.DataFrame({"close": prices[:i]})
        result = strategy.evaluate(df)
        actions.append(result.signal.action)
    return actions


def test_required_history():
    strategy = BollingerBreakoutStrategy(period=20)
    assert strategy.required_history() == 25


def test_detects_upper_band_breakout():
    strategy = BollingerBreakoutStrategy()
    actions = _run(strategy, _tight_range_then_breakout_up())
    assert actions.count("BUY") >= 1
    assert actions.count("SELL") == 0


def test_detects_lower_band_breakdown():
    strategy = BollingerBreakoutStrategy()
    actions = _run(strategy, _tight_range_then_breakdown())
    assert actions.count("SELL") >= 1
    assert actions.count("BUY") == 0


def test_bands_ordered_upper_mid_lower():
    strategy = BollingerBreakoutStrategy()
    df = pd.DataFrame({"close": _tight_range_then_breakout_up()})
    result = strategy.evaluate(df)
    assert result.indicators["bb_upper"] >= result.indicators["bb_mid"] >= result.indicators["bb_lower"]
