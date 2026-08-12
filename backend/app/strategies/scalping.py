from __future__ import annotations

import pandas as pd

from app.indicators import ema
from app.strategies.base import EvaluationResult, Signal


class ScalpingStrategy:
    """Very fast EMA crossover meant to fire often, paired with a tight
    stop/target so each trade risks little — many small trades instead of
    a few large ones. Sets its own SL/TP on every signal (rather than relying
    on OrderService's default distances) so the scalp stays tight regardless
    of what other strategies are configured for.

    A fast/slow EMA pair crosses back and forth constantly in a ranging
    market, so a fresh crossover alone isn't enough — it also counts how many
    times the two EMAs swapped sides over the recent window, and skips the
    entry when that count is high (chop), even though a crossover just fired."""

    id = "scalping"
    display_name = "סקלפינג אגרסיבי (EMA מהיר)"

    def __init__(
        self,
        fast: int = 3,
        slow: int = 8,
        stop_distance: float = 2.5,
        target_distance: float = 4.0,
        chop_lookback: int = 15,
        chop_max_crosses: int = 3,
    ):
        self.fast = fast
        self.slow = slow
        self.stop_distance = stop_distance
        self.target_distance = target_distance
        self.chop_lookback = chop_lookback
        self.chop_max_crosses = chop_max_crosses

    def required_history(self) -> int:
        return self.slow + self.chop_lookback + 1

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        close = candles["close"]
        ema_fast = ema(close, self.fast)
        ema_slow = ema(close, self.slow)

        fast_now, fast_prev = float(ema_fast.iloc[-1]), float(ema_fast.iloc[-2])
        slow_now, slow_prev = float(ema_slow.iloc[-1]), float(ema_slow.iloc[-2])
        price = float(close.iloc[-1])

        # Count sign flips of (fast - slow) over the lookback window — a
        # proxy for "the EMAs are chopping back and forth" rather than
        # committing to one side.
        above_slow = (ema_fast - ema_slow).tail(self.chop_lookback + 1) > 0
        cross_count = int((above_slow != above_slow.shift(1)).iloc[1:].sum())
        choppy = cross_count > self.chop_max_crosses

        indicators = {
            "price": round(price, 2),
            "ema_fast": round(fast_now, 2),
            "ema_slow": round(slow_now, 2),
            "cross_count": float(cross_count),
        }

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now
        bias = "BUY" if fast_now > slow_now else "SELL"

        if crossed_up and not choppy:
            thought = "המחיר התחיל לזנק למעלה, נכנס לקנייה מהירה."
            signal = Signal(
                action="BUY",
                reason=thought,
                stop_loss=price - self.stop_distance,
                take_profit=price + self.target_distance,
            )
        elif crossed_down and not choppy:
            thought = "המחיר התחיל לרדת, נכנס למכירה מהירה."
            signal = Signal(
                action="SELL",
                reason=thought,
                stop_loss=price + self.stop_distance,
                take_profit=price - self.target_distance,
            )
        elif crossed_up or crossed_down:
            thought = (
                f"יש חצייה אבל השוק מדשדש (הצטלבו {cross_count} פעמים "
                f"ב-{self.chop_lookback} הנרות האחרונים) — מדלג על הכניסה."
            )
            signal = Signal(action="NONE", reason=thought)
        else:
            thought = (
                "המחיר נוטה לעלייה, ממתין לרגע הנכון להיכנס (לקניה)."
                if bias == "BUY"
                else "המחיר נוטה לירידה, ממתין לרגע הנכון להיכנס (למכירה)."
            )
            signal = Signal(action="NONE", reason=thought)

        return EvaluationResult(thought=thought, signal=signal, indicators=indicators, bias=bias)
