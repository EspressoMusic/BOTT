import pandas as pd
import pytest

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
    atr = buy_result.indicators["atr"]
    expected_stop_dist = max(strategy.stop_distance, strategy.stop_atr_mult * atr)
    expected_target_dist = max(strategy.target_distance, strategy.target_atr_mult * atr)
    assert buy_result.signal.stop_loss == pytest.approx(buy_result.indicators["price"] - expected_stop_dist)
    assert buy_result.signal.take_profit == pytest.approx(buy_result.indicators["price"] + expected_target_dist)


def test_stop_and_target_widen_past_the_fixed_floor_on_a_volatile_instrument():
    # Regression test: a fixed $2.5/$4.0 stop/target (tuned for gold, spread
    # ~$0.20) is invalid on a broker quoting BTC with a much wider spread
    # (~$23 seen live) — MT5 rejects the order outright. BTC-scale per-bar
    # moves (tens of dollars) should push the ATR-scaled distance past the
    # fixed floor automatically, without a separate instrument-specific code
    # path.
    strategy = ScalpingStrategy()
    down = [63000 - i * 20 for i in range(30)]
    up = [down[-1] + i * 30 for i in range(30)]
    results = _run(strategy, down + up)

    buy_result = next(r for r in results if r.signal.action == "BUY")
    atr = buy_result.indicators["atr"]
    assert atr * strategy.stop_atr_mult > strategy.stop_distance  # ATR term actually dominates here
    # atr here is the rounded indicator value, not the exact float the strategy
    # sized off internally — a loose tolerance absorbs that rounding.
    stop_dist = buy_result.indicators["price"] - buy_result.signal.stop_loss
    target_dist = buy_result.signal.take_profit - buy_result.indicators["price"]
    assert stop_dist == pytest.approx(strategy.stop_atr_mult * atr, abs=0.05)
    assert target_dist == pytest.approx(strategy.target_atr_mult * atr, abs=0.05)


def test_inflated_atr_from_a_stale_spike_is_capped_as_pct_of_price():
    # Regression test for a real live bug: right after a strategy-engine
    # restart, one freak candle sitting in the 200-bar seed window (bad tick,
    # brief flash move) inflates the ATR(14) EWM; because atr() is recomputed
    # from scratch over the whole window on every call, that inflated value
    # takes ~an ATR-period's worth of new candles (~an hour, for period=14)
    # to decay back to normal. A real trade got a $928 stop / $904 target on
    # BTC (atr=366.53) while the instrument's steady-state ATR was ~$7 —
    # atr_mult * atr sailed straight past the fixed floor with nothing to
    # stop it. The pct-of-price ceiling must hold even while ATR is this far
    # from settled.
    strategy = ScalpingStrategy()
    spike = [63000.0, 63000.0, 63600.0]  # one ~$600 jump seeds a huge true range
    calm = [63600.0 + i * 0.5 for i in range(1, 40)]  # decays slowly, still elevated
    down = [calm[-1] - i * 1.0 for i in range(1, 10)]
    up = [down[-1] + i * 1.5 for i in range(1, 10)]
    results = _run(strategy, spike + calm + down + up)

    entry_results = [r for r in results if r.signal.action in ("BUY", "SELL")]
    assert entry_results, "expected at least one entry once the crossover fires"
    for r in entry_results:
        price = r.indicators["price"]
        stop_dist = abs(price - r.signal.stop_loss)
        target_dist = abs(r.signal.take_profit - price)
        assert stop_dist <= price * strategy.max_stop_pct + 1e-6
        assert target_dist <= price * strategy.max_target_pct + 1e-6


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
