import pytest

from app.condition_dsl import evaluate_condition


def test_simple_comparison_against_constant():
    assert evaluate_condition({"left": "rsi", "op": ">", "right": 70}, {"rsi": 75}) is True
    assert evaluate_condition({"left": "rsi", "op": ">", "right": 70}, {"rsi": 65}) is False


def test_comparison_between_two_indicators():
    node = {"left": "ema_fast", "op": ">", "right": "ema_slow"}
    assert evaluate_condition(node, {"ema_fast": 10, "ema_slow": 5}) is True
    assert evaluate_condition(node, {"ema_fast": 3, "ema_slow": 5}) is False


def test_all_combinator_requires_every_condition():
    node = {"all": [{"left": "rsi", "op": "<", "right": 70}, {"left": "price", "op": ">", "right": 100}]}
    assert evaluate_condition(node, {"rsi": 50, "price": 150}) is True
    assert evaluate_condition(node, {"rsi": 80, "price": 150}) is False


def test_any_combinator_requires_one_condition():
    node = {"any": [{"left": "rsi", "op": ">", "right": 70}, {"left": "rsi", "op": "<", "right": 30}]}
    assert evaluate_condition(node, {"rsi": 75}) is True
    assert evaluate_condition(node, {"rsi": 50}) is False


def test_crosses_above_needs_prev_values():
    node = {"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}
    prev = {"ema_fast": 9, "ema_slow": 10}
    now = {"ema_fast": 11, "ema_slow": 10}
    assert evaluate_condition(node, now, prev) is True
    assert evaluate_condition(node, now, None) is False  # no prev snapshot -> can't detect a cross


def test_crosses_below():
    node = {"left": "ema_fast", "op": "crosses_below", "right": "ema_slow"}
    prev = {"ema_fast": 11, "ema_slow": 10}
    now = {"ema_fast": 9, "ema_slow": 10}
    assert evaluate_condition(node, now, prev) is True


def test_missing_indicator_is_false_not_an_error():
    node = {"left": "missing_indicator", "op": ">", "right": 1}
    assert evaluate_condition(node, {"rsi": 50}) is False


def test_unknown_operator_raises():
    with pytest.raises(ValueError):
        evaluate_condition({"left": "rsi", "op": "nonsense", "right": 1}, {"rsi": 50})
