from __future__ import annotations

import pandas as pd

from app.indicators import macd
from app.strategies.base import EvaluationResult, Signal


class MacdTrendStrategy:
    id = "macd_trend"
    display_name = "MACD — מגמה"

    def __init__(self, fast: int = 12, slow: int = 26, signal_period: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal_period = signal_period

    def required_history(self) -> int:
        return self.slow + self.signal_period + 5

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        close = candles["close"]
        macd_line, signal_line, histogram = macd(close, self.fast, self.slow, self.signal_period)

        macd_now, macd_prev = float(macd_line.iloc[-1]), float(macd_line.iloc[-2])
        sig_now, sig_prev = float(signal_line.iloc[-1]), float(signal_line.iloc[-2])
        hist_now = float(histogram.iloc[-1])
        price = float(close.iloc[-1])

        indicators = {
            "price": round(price, 2),
            "macd": round(macd_now, 3),
            "macd_signal": round(sig_now, 3),
            "macd_hist": round(hist_now, 3),
        }

        crossed_up = macd_prev <= sig_prev and macd_now > sig_now
        crossed_down = macd_prev >= sig_prev and macd_now < sig_now
        bias = "BUY" if macd_now > sig_now else "SELL"

        if crossed_up:
            thought = "המומנטום פנה כלפי מעלה, נכנס לקנייה."
            signal = Signal(action="BUY", reason=thought)
        elif crossed_down:
            thought = "המומנטום פנה כלפי מטה, נכנס למכירה."
            signal = Signal(action="SELL", reason=thought)
        elif bias == "BUY":
            thought = "המומנטום עדיין חיובי, נשאר בצד (לקניה)."
            signal = Signal(action="NONE", reason=thought)
        else:
            thought = "המומנטום עדיין שלילי, נשאר בצד (למכירה)."
            signal = Signal(action="NONE", reason=thought)

        return EvaluationResult(thought=thought, signal=signal, indicators=indicators, bias=bias)
