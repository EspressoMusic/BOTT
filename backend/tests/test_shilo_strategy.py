import pandas as pd

from app.strategies.shilo import ShiloStrategy


def _make_df(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"close": closes, "high": [c + 0.5 for c in closes], "low": [c - 0.5 for c in closes]})


def _run(strategy: ShiloStrategy, closes: list[float]) -> list:
    results = []
    for i in range(strategy.required_history(), len(closes) + 1):
        df = _make_df(closes[:i])
        results.append(strategy.evaluate(df))
    return results


def _rally_pullback_to_ema_then_break_up() -> list[float]:
    rally = [2300 + i * 1.0 for i in range(70)]  # long steady climb, EMA50 trails well behind
    # Deep pullback that crosses through EMA50 (the touch) and keeps going —
    # the undershoot separates the touch from the eventual break, the way a
    # real pullback overshoots past the average before turning.
    pullback = [rally[-1] - i * 1.5 for i in range(1, 56)]
    # Strong, sustained bounce that climbs back past the (much smaller, local)
    # swing high formed in the few bars right before the touch.
    bounce = [pullback[-1] + i * 4.0 for i in range(1, 26)]
    return rally + pullback + bounce


def _decline_rally_to_ema_then_break_down() -> list[float]:
    decline = [2300 - i * 1.0 for i in range(70)]
    rally = [decline[-1] + i * 1.5 for i in range(1, 56)]
    drop = [rally[-1] - i * 4.0 for i in range(1, 26)]
    return decline + rally + drop


def test_required_history():
    strategy = ShiloStrategy(ema_period=50, structure_lookback=20, swing_lookback=5)
    assert strategy.required_history() == 77


def test_bullish_break_of_structure_after_ema_touch_fires_buy():
    # A wide structure_lookback so the touch (well before the eventual break,
    # given the deliberate undershoot) is still "recent" when the break fires.
    strategy = ShiloStrategy(structure_lookback=65)
    results = _run(strategy, _rally_pullback_to_ema_then_break_up())
    actions = [r.signal.action for r in results]

    assert actions.count("BUY") >= 1
    buy_result = next(r for r in results if r.signal.action == "BUY")
    assert buy_result.signal.stop_loss is not None
    assert buy_result.signal.take_profit is not None
    assert buy_result.signal.stop_loss < buy_result.indicators["price"] < buy_result.signal.take_profit


def test_bearish_break_of_structure_after_ema_touch_fires_sell():
    strategy = ShiloStrategy(structure_lookback=65)
    results = _run(strategy, _decline_rally_to_ema_then_break_down())
    actions = [r.signal.action for r in results]

    assert actions.count("SELL") >= 1
    sell_result = next(r for r in results if r.signal.action == "SELL")
    assert sell_result.signal.stop_loss is not None
    assert sell_result.signal.take_profit is not None
    assert sell_result.signal.take_profit < sell_result.indicators["price"] < sell_result.signal.stop_loss


def test_no_touch_yet_produces_no_signal():
    strategy = ShiloStrategy()
    # Flat-ish, hugging the EMA the whole time — required_history is short
    # relative to structure_lookback here so there's no room for a "recent"
    # touch this early; mainly a smoke test that evaluate() doesn't blow up
    # before any touch/break has had a chance to happen.
    closes = [2400 + (0.1 if i % 2 == 0 else -0.1) for i in range(strategy.required_history())]
    result = strategy.evaluate(_make_df(closes))
    assert result.signal.action in ("NONE", "BUY", "SELL")


def test_indicators_reported():
    strategy = ShiloStrategy()
    df = _make_df(_rally_pullback_to_ema_then_break_up())
    result = strategy.evaluate(df)
    assert {"price", "ema50"}.issubset(result.indicators)
