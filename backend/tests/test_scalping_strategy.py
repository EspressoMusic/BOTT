import pandas as pd

from app.strategies.scalping import ScalpingStrategy


def _make_df(closes: list[float]) -> pd.DataFrame:
    # No real OHLC in these synthetic tests — high=low=close collapses the
    # true-range formula down to a plain |close - prev_close| move size,
    # which is exactly the "how big was this step vs. the recent average"
    # signal the spike filter needs.
    return pd.DataFrame({"close": closes, "high": closes, "low": closes})


def _run(strategy: ScalpingStrategy, closes: list[float]) -> list:
    results = []
    for i in range(strategy.required_history(), len(closes) + 1):
        df = _make_df(closes[:i])
        results.append(strategy.evaluate(df))
    return results


def test_required_history():
    strategy = ScalpingStrategy(slow=8, chop_lookback=15, atr_period=14)
    assert strategy.required_history() == 25


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


def test_sudden_spike_suppresses_entry_even_without_chop():
    # A calm, steady uptrend (small uniform steps, fast EMA riding above
    # slow) that suddenly craters on one huge bar — precisely the "price was
    # fine, then suddenly starts falling fast" shape that shouldn't be
    # chased into a SELL. Not choppy (no back-and-forth before it), just one
    # outlier bar flipping the crossover.
    strategy = ScalpingStrategy()
    steady = [2400 + i * 0.3 for i in range(25)]
    spike = [steady[-1] - 15.0]  # one bar, ~50x the recent per-bar step
    results = _run(strategy, steady + spike)

    spike_result = next(r for r in results if "זינק חד מדי" in r.thought or "ספייק" in r.thought)
    assert spike_result.signal.action == "NONE"


def test_recovery_after_decline_is_not_reported_as_still_falling():
    # A decline establishes a SELL bias (fast EMA below slow), then price
    # starts recovering — the fast EMA turns up while the slower one is
    # still catching down from the decline, so bias stays SELL for a few
    # bars even though price itself is now rising. The thought shouldn't
    # claim the price is "trending down" while that's happening.
    strategy = ScalpingStrategy()
    decline = [2420 - i * 0.6 for i in range(30)]
    recovery = [decline[-1] + i * 0.3 for i in range(1, 4)]
    results = _run(strategy, decline + recovery)

    waiting = [r for r in results if r.bias == "SELL" and r.signal.action == "NONE"]
    assert any("מתאושש" in r.thought for r in waiting)


def test_indicators_reported():
    strategy = ScalpingStrategy()
    closes = [2400 + i * 0.3 for i in range(30)]
    result = strategy.evaluate(_make_df(closes))
    assert set(result.indicators) == {"price", "ema_fast", "ema_slow", "cross_count", "atr"}
