import pandas as pd

from app.strategies.rule_based import RuleBasedStrategy


def _ema_crossover_dsl() -> dict:
    return {
        "indicators": [
            {"name": "ema_fast", "type": "EMA", "period": 9},
            {"name": "ema_slow", "type": "EMA", "period": 21},
        ],
        "entry_long": {"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"},
        "entry_short": {"left": "ema_fast", "op": "crosses_below", "right": "ema_slow"},
        "stop_loss": {"type": "distance", "value": 10.0},
        "take_profit": {"type": "distance", "value": 20.0},
    }


def _prices_down_then_up() -> list[float]:
    down = [110 - i * 0.5 for i in range(30)]
    up = [95.5 + i * 1.5 for i in range(30)]
    return down + up


def test_required_history_uses_largest_indicator_period():
    strategy = RuleBasedStrategy("custom-1", "test strategy", _ema_crossover_dsl())
    assert strategy.required_history() == 21 + 5


def test_replicates_ema_crossover_behavior():
    strategy = RuleBasedStrategy("custom-1", "test strategy", _ema_crossover_dsl())
    prices = _prices_down_then_up()

    actions = []
    for i in range(strategy.required_history(), len(prices) + 1):
        df = pd.DataFrame({"close": prices[:i]})
        result = strategy.evaluate(df)
        actions.append(result.signal.action)

    assert actions.count("BUY") == 1
    assert actions.count("SELL") == 0


def test_stop_loss_and_take_profit_computed_from_distance_spec():
    strategy = RuleBasedStrategy("custom-1", "test strategy", _ema_crossover_dsl())
    prices = _prices_down_then_up()

    for i in range(strategy.required_history(), len(prices) + 1):
        df = pd.DataFrame({"close": prices[:i]})
        result = strategy.evaluate(df)
        if result.signal.action == "BUY":
            price = result.indicators["price"]
            assert result.signal.stop_loss == price - 10.0
            assert result.signal.take_profit == price + 20.0
            return
    raise AssertionError("expected a BUY signal during this price path")


def test_no_conditions_configured_means_no_signal():
    strategy = RuleBasedStrategy("custom-2", "empty strategy", {"indicators": []})
    df = pd.DataFrame({"close": [100.0] * 30})
    result = strategy.evaluate(df)
    assert result.signal.action == "NONE"
