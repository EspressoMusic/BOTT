import pandas as pd

from app.strategies.scalping import ScalpingStrategy


def _make_df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes})


def _run(strategy: ScalpingStrategy, closes: list[float]) -> list:
    results = []
    for i in range(strategy.required_history(), len(closes) + 1):
        df = _make_df(closes[:i])
        results.append(strategy.evaluate(df))
    return results


def test_required_history():
    strategy = ScalpingStrategy(slow=8, chop_lookback=15)
    assert strategy.required_history() == 24


def test_clean_trend_fires_entry_with_tight_stops():
    strategy = ScalpingStrategy()
    down = [2410 - i * 0.5 for i in range(30)]
    up = [down[-1] + i * 1.0 for i in range(30)]
    results = _run(strategy, down + up)
    actions = [r.signal.action for r in results]

    assert actions.count("BUY") >= 1
    assert actions.count("SELL") == 0

    buy_result = next(r for r in results if r.signal.action == "BUY")
    assert buy_result.signal.stop_loss == round(buy_result.indicators["price"] - strategy.stop_distance, 2)
    assert buy_result.signal.take_profit == round(buy_result.indicators["price"] + strategy.target_distance, 2)


def test_choppy_market_suppresses_entries():
    strategy = ScalpingStrategy()
    base, amp, period = 2400.0, 3.0, 4
    closes = [base + (amp if (i // period) % 2 == 0 else -amp) for i in range(60)]
    results = _run(strategy, closes)
    actions = [r.signal.action for r in results]

    assert actions.count("BUY") == 0
    assert actions.count("SELL") == 0
    assert any(r.indicators["cross_count"] > strategy.chop_max_crosses for r in results)


def test_indicators_reported():
    strategy = ScalpingStrategy()
    closes = [2400 + i * 0.3 for i in range(30)]
    result = strategy.evaluate(_make_df(closes))
    assert set(result.indicators) == {"price", "ema_fast", "ema_slow", "cross_count"}
