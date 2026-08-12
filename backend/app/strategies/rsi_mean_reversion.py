from __future__ import annotations

import pandas as pd

from app.indicators import rsi
from app.strategies.base import EvaluationResult, Signal


class RsiMeanReversionStrategy:
    id = "rsi_mean_reversion"
    display_name = "RSI — חזרה לממוצע"

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0):
        self.period = period
        self.oversold = oversold
        self.overbought = overbought

    def required_history(self) -> int:
        return self.period + 5

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        close = candles["close"]
        rsi_series = rsi(close, self.period)

        rsi_now, rsi_prev = float(rsi_series.iloc[-1]), float(rsi_series.iloc[-2])
        price = float(close.iloc[-1])

        indicators = {"price": round(price, 2), "rsi": round(rsi_now, 2)}

        left_oversold = rsi_prev < self.oversold <= rsi_now
        left_overbought = rsi_prev > self.overbought >= rsi_now

        bias = "BUY" if rsi_now < self.oversold else "SELL" if rsi_now > self.overbought else None

        if left_oversold:
            thought = "השוק היה מכור יתר על המידה ומתחיל להתאושש, נכנס לקנייה."
            signal = Signal(action="BUY", reason=thought)
        elif left_overbought:
            thought = "השוק היה קנוי יתר על המידה ומתחיל לרדת, נכנס למכירה."
            signal = Signal(action="SELL", reason=thought)
        elif rsi_now < self.oversold:
            thought = "השוק נראה מכור יתר על המידה, ממתין לסימן התאוששות (לקניה)."
            signal = Signal(action="NONE", reason=thought)
        elif rsi_now > self.overbought:
            thought = "השוק נראה קנוי יתר על המידה, ממתין לסימן היפוך (למכירה)."
            signal = Signal(action="NONE", reason=thought)
        else:
            thought = "אין קיצוניות כרגע בשוק, פשוט עוקב אחריו."
            signal = Signal(action="NONE", reason=thought)

        return EvaluationResult(thought=thought, signal=signal, indicators=indicators, bias=bias)
