from __future__ import annotations

import pandas as pd

from app.indicators import bollinger_bands
from app.strategies.base import EvaluationResult, Signal


class BollingerBreakoutStrategy:
    id = "bollinger_breakout"
    display_name = "פריצת רצועות בולינגר"

    def __init__(self, period: int = 20, num_std: float = 2.0):
        self.period = period
        self.num_std = num_std

    def required_history(self) -> int:
        return self.period + 5

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        close = candles["close"]
        upper, mid, lower = bollinger_bands(close, self.period, self.num_std)

        price_now, price_prev = float(close.iloc[-1]), float(close.iloc[-2])
        upper_now, upper_prev = float(upper.iloc[-1]), float(upper.iloc[-2])
        lower_now, lower_prev = float(lower.iloc[-1]), float(lower.iloc[-2])
        mid_now = float(mid.iloc[-1])

        indicators = {
            "price": round(price_now, 2),
            "bb_upper": round(upper_now, 2),
            "bb_mid": round(mid_now, 2),
            "bb_lower": round(lower_now, 2),
        }

        broke_up = price_prev <= upper_prev and price_now > upper_now
        broke_down = price_prev >= lower_prev and price_now < lower_now
        bias = "BUY" if price_now > mid_now else "SELL"

        if broke_up:
            thought = "המחיר פרץ החוצה כלפי מעלה, נכנס לקנייה."
            signal = Signal(action="BUY", reason=thought)
        elif broke_down:
            thought = "המחיר פרץ החוצה כלפי מטה, נכנס למכירה."
            signal = Signal(action="SELL", reason=thought)
        else:
            thought = (
                "המחיר נע בטווח רגיל, ממתין לפריצה (לקניה)."
                if bias == "BUY"
                else "המחיר נע בטווח רגיל, ממתין לפריצה (למכירה)."
            )
            signal = Signal(action="NONE", reason=thought)

        return EvaluationResult(thought=thought, signal=signal, indicators=indicators, bias=bias)
