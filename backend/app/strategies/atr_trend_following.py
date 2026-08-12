from __future__ import annotations

import pandas as pd

from app.indicators import atr, sma
from app.strategies.base import EvaluationResult, Signal


class AtrTrendFollowingStrategy:
    id = "atr_trend_following"
    display_name = "מגמה מבוססת ATR"

    def __init__(
        self,
        trend_period: int = 20,
        atr_period: int = 14,
        atr_stop_mult: float = 2.0,
        atr_target_mult: float = 3.0,
    ):
        self.trend_period = trend_period
        self.atr_period = atr_period
        self.atr_stop_mult = atr_stop_mult
        self.atr_target_mult = atr_target_mult

    def required_history(self) -> int:
        return max(self.trend_period, self.atr_period) + 5

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        close = candles["close"]
        trend = sma(close, self.trend_period)
        atr_series = atr(candles["high"], candles["low"], close, self.atr_period)

        price_now, price_prev = float(close.iloc[-1]), float(close.iloc[-2])
        trend_now, trend_prev = float(trend.iloc[-1]), float(trend.iloc[-2])
        atr_now = float(atr_series.iloc[-1])

        indicators = {"price": round(price_now, 2), "sma_trend": round(trend_now, 2), "atr": round(atr_now, 2)}

        crossed_up = price_prev <= trend_prev and price_now > trend_now
        crossed_down = price_prev >= trend_prev and price_now < trend_now
        bias = "BUY" if price_now > trend_now else "SELL"

        if crossed_up:
            stop_loss = price_now - self.atr_stop_mult * atr_now
            take_profit = price_now + self.atr_target_mult * atr_now
            thought = "המחיר חצה מעל הממוצע, נכנס לקנייה."
            signal = Signal(action="BUY", reason=thought, stop_loss=stop_loss, take_profit=take_profit)
        elif crossed_down:
            stop_loss = price_now + self.atr_stop_mult * atr_now
            take_profit = price_now - self.atr_target_mult * atr_now
            thought = "המחיר חצה מתחת לממוצע, נכנס למכירה."
            signal = Signal(action="SELL", reason=thought, stop_loss=stop_loss, take_profit=take_profit)
        elif bias == "BUY":
            thought = "המחיר נשאר מעל הממוצע, ממשיך לעקוב (לקניה)."
            signal = Signal(action="NONE", reason=thought)
        else:
            thought = "המחיר נשאר מתחת לממוצע, ממשיך לעקוב (למכירה)."
            signal = Signal(action="NONE", reason=thought)

        return EvaluationResult(thought=thought, signal=signal, indicators=indicators, bias=bias)
