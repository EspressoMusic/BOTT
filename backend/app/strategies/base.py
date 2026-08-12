"""Shared contract every strategy (built-in or, later, user-defined) implements.
Every evaluation produces a `thought` (always, even when there's no signal) and a
`signal` (usually NONE) from the same indicator computation — so the engine never
computes indicators twice for "what should I say" vs. "what should I do".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

import pandas as pd

Action = Literal["NONE", "BUY", "SELL", "CLOSE"]
Bias = Literal["BUY", "SELL"]


@dataclass
class Signal:
    action: Action
    reason: str
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass
class EvaluationResult:
    thought: str
    signal: Signal
    indicators: dict[str, float] = field(default_factory=dict)
    # Which way the strategy currently leans, even while `signal.action` is NONE —
    # lets the UI show an intent arrow ("leaning to buy") while it's still waiting
    # for its actual entry trigger.
    bias: Bias | None = None


class Strategy(Protocol):
    id: str
    display_name: str

    def required_history(self) -> int:
        """Minimum number of candles needed before evaluate() can run."""

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        """`candles` has open/high/low/close columns, ascending by time."""
