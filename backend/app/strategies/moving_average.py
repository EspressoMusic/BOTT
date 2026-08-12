from __future__ import annotations

import pandas as pd

from app.indicators import ema
from app.strategies.base import EvaluationResult, Signal


class MovingAverageCrossoverStrategy:
    id = "ma_crossover"
    display_name = "חציית ממוצעים נעים (EMA)"

    def __init__(self, fast: int = 9, slow: int = 21):
        self.fast = fast
        self.slow = slow

    def required_history(self) -> int:
        return self.slow + 5

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        close = candles["close"]
        ema_fast = ema(close, self.fast)
        ema_slow = ema(close, self.slow)

        fast_now, fast_prev = float(ema_fast.iloc[-1]), float(ema_fast.iloc[-2])
        slow_now, slow_prev = float(ema_slow.iloc[-1]), float(ema_slow.iloc[-2])
        price = float(close.iloc[-1])

        indicators = {
            "price": round(price, 2),
            "ema_fast": round(fast_now, 2),
            "ema_slow": round(slow_now, 2),
        }

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now
        bias = "BUY" if fast_now > slow_now else "SELL"

        if crossed_up:
            thought = "המגמה התהפכה לעלייה, נכנס לקנייה."
            signal = Signal(action="BUY", reason=thought)
        elif crossed_down:
            thought = "המגמה התהפכה לירידה, נכנס למכירה."
            signal = Signal(action="SELL", reason=thought)
        elif bias == "BUY":
            thought = "המגמה עדיין עולה, לא רואה סיבה להתערב (לקניה)."
            signal = Signal(action="NONE", reason=thought)
        else:
            thought = "המגמה עדיין יורדת, ממתין לשינוי (למכירה)."
            signal = Signal(action="NONE", reason=thought)

        return EvaluationResult(thought=thought, signal=signal, indicators=indicators, bias=bias)
