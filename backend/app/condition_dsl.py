"""Shared declarative condition grammar used by both custom strategies and
feedback rules: a small tree of comparisons over named indicator values,
combined with all/any. No code execution — see plan rationale (security: never
eval arbitrary user-submitted code).

{"all": [{"left": "rsi", "op": "<", "right": 70}, {"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}]}
{"any": [...]}
{"left": "ema_fast", "op": ">", "right": "ema_slow"}          -- "right" may be a number or another indicator name
{"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}  -- needs prev_values (the prior bar's snapshot)
"""

from __future__ import annotations

_COMPARATORS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


def _resolve(operand: float | str, values: dict[str, float]) -> float | None:
    if isinstance(operand, str):
        return values.get(operand)
    return operand


def evaluate_condition(
    node: dict,
    values: dict[str, float],
    prev_values: dict[str, float] | None = None,
) -> bool:
    if "all" in node:
        return all(evaluate_condition(child, values, prev_values) for child in node["all"])
    if "any" in node:
        return any(evaluate_condition(child, values, prev_values) for child in node["any"])

    op = node["op"]
    left_val = _resolve(node["left"], values)
    right_val = _resolve(node["right"], values)
    if left_val is None or right_val is None:
        return False

    if op in _COMPARATORS:
        return _COMPARATORS[op](left_val, right_val)

    if op in ("crosses_above", "crosses_below"):
        if prev_values is None:
            return False
        prev_left = _resolve(node["left"], prev_values)
        prev_right = _resolve(node["right"], prev_values)
        if prev_left is None or prev_right is None:
            return False
        if op == "crosses_above":
            return prev_left <= prev_right and left_val > right_val
        return prev_left >= prev_right and left_val < right_val

    raise ValueError(f"Unknown condition operator: {op!r}")
