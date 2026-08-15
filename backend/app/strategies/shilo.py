from __future__ import annotations

import pandas as pd

from app.indicators import ema
from app.strategies.base import EvaluationResult, Signal


class ShiloStrategy:
    """EMA-50 pullback + break-of-structure confirmation.

    Waits for price to touch the EMA-50 (a candle whose [low, high] range
    crosses the line) — that touch alone is never a signal, just a candidate
    pullback point. From there it watches the swing that formed in the
    `swing_lookback` bars right before the touch (its highest high / lowest
    low), and only fires once price actually breaks back through that swing
    afterward:
    - breaks above the pre-touch swing high -> BUY (e.g. price ran up,
      pulled back down onto the EMA, then pushed back above the level it
      pulled back from).
    - breaks below the pre-touch swing low -> SELL (the mirror case: price
      ran down, rallied back up onto the EMA, then pushed back below).

    The stop sits just past the pullback's own extreme (the lowest low / the
    highest high actually reached between the touch and the breakout) — if
    price revisits that, the structure this trade is betting on already
    failed. Target is a fixed reward:risk multiple of that stop distance.
    """

    id = "shilo"
    display_name = "שילה — מגע EMA50 ושבירת מבנה שוק"

    def __init__(
        self,
        ema_period: int = 50,
        structure_lookback: int = 20,
        swing_lookback: int = 5,
        reward_risk_ratio: float = 2.0,
        stop_buffer: float = 0.3,
    ):
        self.ema_period = ema_period
        self.structure_lookback = structure_lookback
        self.swing_lookback = swing_lookback
        self.reward_risk_ratio = reward_risk_ratio
        self.stop_buffer = stop_buffer

    def required_history(self) -> int:
        return self.ema_period + self.structure_lookback + self.swing_lookback + 2

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        close = candles["close"]
        high = candles["high"]
        low = candles["low"]
        ema50 = ema(close, self.ema_period)

        n = len(candles)
        price = float(close.iloc[-1])
        price_prev = float(close.iloc[-2])
        ema_now = float(ema50.iloc[-1])
        bias = "BUY" if price > ema_now else "SELL"
        indicators = {"price": round(price, 2), "ema50": round(ema_now, 2)}

        touched = ((low <= ema50) & (high >= ema50)).to_numpy()

        # Most recent bar strictly before the current one where price
        # touched the EMA, searching back only `structure_lookback` bars.
        search_start = max(0, n - 1 - self.structure_lookback)
        touch_pos = next((i for i in range(n - 2, search_start - 1, -1) if touched[i]), None)

        if touch_pos is None:
            thought = (
                "ממתין שהמחיר ייגע ב-EMA50 (לקניה)." if bias == "BUY" else "ממתין שהמחיר ייגע ב-EMA50 (למכירה)."
            )
            signal = Signal(action="NONE", reason=thought)
            return EvaluationResult(thought=thought, signal=signal, indicators=indicators, bias=bias)

        swing_start = max(0, touch_pos - self.swing_lookback)
        swing_high = float(high.iloc[swing_start:touch_pos].max()) if touch_pos > swing_start else float(high.iloc[touch_pos])
        swing_low = float(low.iloc[swing_start:touch_pos].min()) if touch_pos > swing_start else float(low.iloc[touch_pos])
        indicators["swing_high"] = round(swing_high, 2)
        indicators["swing_low"] = round(swing_low, 2)

        broke_up = price_prev <= swing_high and price > swing_high
        broke_down = price_prev >= swing_low and price < swing_low

        # The pullback's own extreme between the touch and the breakout —
        # the invalidation point for whichever structure just broke.
        pullback_low = float(low.iloc[touch_pos : n - 1].min())
        pullback_high = float(high.iloc[touch_pos : n - 1].max())

        if broke_up:
            stop_loss = pullback_low - self.stop_buffer
            take_profit = price + self.reward_risk_ratio * (price - stop_loss)
            thought = "המחיר נגע ב-EMA50 ואז שבר את השיא שקדם לו (מבנה שוק כלפי מעלה) — נכנס לקנייה."
            signal = Signal(action="BUY", reason=thought, stop_loss=stop_loss, take_profit=take_profit)
        elif broke_down:
            stop_loss = pullback_high + self.stop_buffer
            take_profit = price - self.reward_risk_ratio * (stop_loss - price)
            thought = "המחיר נגע ב-EMA50 ואז שבר את השפל שקדם לו (מבנה שוק כלפי מטה) — נכנס למכירה."
            signal = Signal(action="SELL", reason=thought, stop_loss=stop_loss, take_profit=take_profit)
        else:
            thought = (
                "המחיר נגע ב-EMA50 לאחרונה, ממתין לשבירת מבנה שוק לאישור כיוון (לקניה)."
                if bias == "BUY"
                else "המחיר נגע ב-EMA50 לאחרונה, ממתין לשבירת מבנה שוק לאישור כיוון (למכירה)."
            )
            signal = Signal(action="NONE", reason=thought)

        return EvaluationResult(thought=thought, signal=signal, indicators=indicators, bias=bias)
