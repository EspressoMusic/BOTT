"""Interprets a user-authored declarative strategy definition (JSON) — no code
execution (see plan rationale: never eval arbitrary user-submitted code). The
rule-builder UI assembles this JSON from dropdowns; users never write it by hand.

dsl_config shape:
{
  "indicators": [{"name": "ema_fast", "type": "EMA", "period": 9}, ...],
  "entry_long":  {"all": [{"left": "ema_fast", "op": "crosses_above", "right": "ema_slow"}]},
  "entry_short": {"all": [...]},                      -- optional
  "stop_loss":   {"type": "distance", "value": 15.0},  -- optional, fixed price distance from entry
  "take_profit": {"type": "distance", "value": 30.0}   -- optional
}
"""

from __future__ import annotations

import pandas as pd

from app.condition_dsl import evaluate_condition
from app.indicators import atr, ema, rsi, sma
from app.strategies.base import EvaluationResult, Signal

_DEFAULT_PERIOD = 14


def _compute_indicator_series(spec: dict, df: pd.DataFrame) -> pd.Series:
    ind_type = spec["type"]
    close = df["close"]
    if ind_type == "EMA":
        return ema(close, spec["period"])
    if ind_type == "SMA":
        return sma(close, spec["period"])
    if ind_type == "RSI":
        return rsi(close, spec.get("period", _DEFAULT_PERIOD))
    if ind_type == "ATR":
        return atr(df["high"], df["low"], close, spec.get("period", _DEFAULT_PERIOD))
    raise ValueError(f"Unsupported indicator type in custom strategy: {ind_type!r}")


class RuleBasedStrategy:
    def __init__(self, strategy_id: str, display_name: str, dsl_config: dict):
        self.id = strategy_id
        self.display_name = display_name
        self._dsl = dsl_config
        self._indicator_specs = dsl_config.get("indicators", [])

    def required_history(self) -> int:
        periods = [spec.get("period", _DEFAULT_PERIOD) for spec in self._indicator_specs]
        return (max(periods) if periods else 20) + 5

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        series_by_name = {spec["name"]: _compute_indicator_series(spec, candles) for spec in self._indicator_specs}

        values = {name: float(s.iloc[-1]) for name, s in series_by_name.items()}
        values["price"] = float(candles["close"].iloc[-1])
        prev_values = {name: float(s.iloc[-2]) for name, s in series_by_name.items()}
        prev_values["price"] = float(candles["close"].iloc[-2])

        entry_long = self._dsl.get("entry_long")
        entry_short = self._dsl.get("entry_short")

        action = "NONE"
        if entry_long and evaluate_condition(entry_long, values, prev_values):
            action = "BUY"
        elif entry_short and evaluate_condition(entry_short, values, prev_values):
            action = "SELL"

        stop_loss = take_profit = None
        if action != "NONE":
            stop_loss = self._resolve_price_offset(self._dsl.get("stop_loss"), values["price"], action, is_stop=True)
            take_profit = self._resolve_price_offset(
                self._dsl.get("take_profit"), values["price"], action, is_stop=False
            )

        indicator_summary = " | ".join(f"{k}={v:.2f}" for k, v in values.items())
        if action == "BUY":
            thought = f"🔼 {self.display_name}: תנאי הכניסה הארוכה התקיימו ({indicator_summary}) — איתות קנייה"
        elif action == "SELL":
            thought = f"🔽 {self.display_name}: תנאי הכניסה הקצרה התקיימו ({indicator_summary}) — איתות מכירה"
        else:
            thought = f"{self.display_name}: {indicator_summary}"

        return EvaluationResult(
            thought=thought,
            signal=Signal(action=action, reason=thought, stop_loss=stop_loss, take_profit=take_profit),
            indicators=values,
        )

    @staticmethod
    def _resolve_price_offset(spec: dict | None, price: float, action: str, is_stop: bool) -> float | None:
        # Only a fixed price-distance offset is supported for now (kept simple —
        # ATR-multiple/risk-reward sizing can be added the same way as the
        # built-in ATR strategy once the rule builder needs it).
        if not spec:
            return None
        direction = 1 if action == "BUY" else -1
        sign = -1 if is_stop else 1
        distance = spec.get("value", 15.0 if is_stop else 30.0)
        return price + sign * direction * distance
