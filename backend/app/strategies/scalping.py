from __future__ import annotations

import pandas as pd

from app.indicators import atr, ema
from app.strategies.base import EvaluationResult, Signal


class ScalpingStrategy:
    """Very fast EMA crossover meant to fire often, paired with a tight
    stop/target so each trade risks little — many small trades instead of
    a few large ones. Sets its own SL/TP on every signal (rather than relying
    on OrderService's default distances) so the scalp stays tight regardless
    of what other strategies are configured for.

    A fast/slow EMA pair crosses back and forth constantly in a ranging
    market, so a fresh crossover alone isn't enough:
    - it counts how many times the two EMAs swapped sides over the recent
      window, and skips the entry when that count is high (chop), even
      though a crossover just fired.
    - it also skips the entry when the crossover candle itself is a volatility
      spike (true range well above the recent ATR) — a sudden sharp bar is
      exactly the kind of move that tends to snap back, so chasing it the
      instant it happens is a bad, "stupid" scalp rather than a real trend
      shift. Better to let a spike like that pass and catch the next, calmer
      crossover.
    """

    id = "scalping"
    display_name = "סקלפינג אגרסיבי (EMA מהיר)"

    def __init__(
        self,
        fast: int = 3,
        slow: int = 8,
        stop_distance: float = 2.5,
        target_distance: float = 4.0,
        stop_atr_mult: float = 2.5,
        target_atr_mult: float = 2.5,
        max_stop_pct: float = 0.0015,
        max_target_pct: float = 0.0024,
        chop_lookback: int = 15,
        chop_max_crosses: int = 3,
        atr_period: int = 14,
        spike_atr_mult: float = 2.5,
    ):
        self.fast = fast
        self.slow = slow
        # Floors, in the instrument's own price units — dollars for XAUUSD/BTCUSD.
        # The actual stop/target used is whichever is bigger, this or
        # {stop,target}_atr_mult * ATR (see evaluate()): a fixed $2.5 stop makes
        # sense for gold (spread ~$0.20) but is invalid on a broker that quotes
        # BTC with a ~$23 spread — MT5 rejects an order whose SL/TP ends up on
        # the wrong side of the fill price once the spread is applied. Scaling
        # with ATR keeps gold's already-tuned behavior (its ATR rarely exceeds
        # these floors) while automatically widening for higher-volatility/
        # wider-spread instruments.
        self.stop_distance = stop_distance
        self.target_distance = target_distance
        self.stop_atr_mult = stop_atr_mult
        self.target_atr_mult = target_atr_mult
        # Ceilings, as a fraction of current price. ATR is recomputed from
        # scratch over the whole candle window on every call (see evaluate());
        # right after a strategy-engine restart, or whenever one freak candle
        # (bad tick, brief flash move) sits in that window, the EWM needs
        # roughly a full ATR-period's worth of new candles to "forget" it —
        # for a 14-period ATR that's close to an hour. Until then ATR can read
        # many times its steady-state value, and stop_atr_mult * ATR would
        # sail past a floor that was only ever tuned for the normal case.
        # These caps bound that failure regardless of what inflated ATR,
        # without hardcoding per-instrument dollar values.
        self.max_stop_pct = max_stop_pct
        self.max_target_pct = max_target_pct
        self.chop_lookback = chop_lookback
        self.chop_max_crosses = chop_max_crosses
        self.atr_period = atr_period
        self.spike_atr_mult = spike_atr_mult

    def required_history(self) -> int:
        return max(self.slow + self.chop_lookback, self.atr_period) + 2

    def evaluate(self, candles: pd.DataFrame) -> EvaluationResult:
        close = candles["close"]
        ema_fast = ema(close, self.fast)
        ema_slow = ema(close, self.slow)
        atr_series = atr(candles["high"], candles["low"], close, self.atr_period)

        fast_now, fast_prev = float(ema_fast.iloc[-1]), float(ema_fast.iloc[-2])
        slow_now, slow_prev = float(ema_slow.iloc[-1]), float(ema_slow.iloc[-2])
        price = float(close.iloc[-1])

        # Count sign flips of (fast - slow) over the lookback window — a
        # proxy for "the EMAs are chopping back and forth" rather than
        # committing to one side.
        above_slow = (ema_fast - ema_slow).tail(self.chop_lookback + 1) > 0
        cross_count = int((above_slow != above_slow.shift(1)).iloc[1:].sum())
        choppy = cross_count > self.chop_max_crosses

        # True range of *this* candle vs. the ATR as of the *previous* bar —
        # deliberately excludes the current bar from its own baseline, so a
        # spike can't inflate the average it's being compared against.
        current_range = max(
            candles["high"].iloc[-1] - candles["low"].iloc[-1],
            abs(candles["high"].iloc[-1] - close.iloc[-2]),
            abs(candles["low"].iloc[-1] - close.iloc[-2]),
        )
        atr_prev = float(atr_series.iloc[-2])
        spiking = atr_prev > 0 and current_range > self.spike_atr_mult * atr_prev

        stop_dist = max(self.stop_distance, self.stop_atr_mult * atr_prev)
        target_dist = max(self.target_distance, self.target_atr_mult * atr_prev)
        stop_dist = min(stop_dist, price * self.max_stop_pct)
        target_dist = min(target_dist, price * self.max_target_pct)

        indicators = {
            "price": round(price, 2),
            "ema_fast": round(fast_now, 2),
            "ema_slow": round(slow_now, 2),
            "cross_count": float(cross_count),
            "atr": round(atr_prev, 2),
        }

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now
        bias = "BUY" if fast_now > slow_now else "SELL"

        if crossed_up and not choppy and not spiking:
            thought = "המחיר התחיל לזנק למעלה, נכנס לקנייה מהירה."
            signal = Signal(
                action="BUY",
                reason=thought,
                stop_loss=price - stop_dist,
                take_profit=price + target_dist,
            )
        elif crossed_down and not choppy and not spiking:
            thought = "המחיר התחיל לרדת, נכנס למכירה מהירה."
            signal = Signal(
                action="SELL",
                reason=thought,
                stop_loss=price + stop_dist,
                take_profit=price - target_dist,
            )
        elif (crossed_up or crossed_down) and spiking:
            thought = (
                "יש חצייה אבל הנר הזה זינק חד מדי (טווח גדול פי "
                f"{current_range / atr_prev:.1f} מה-ATR הרגיל) — נראה כמו ספייק שעלול לחזור אחורה, מדלג על הכניסה."
            )
            signal = Signal(action="NONE", reason=thought)
        elif crossed_up or crossed_down:
            thought = (
                f"יש חצייה אבל השוק מדשדש (הצטלבו {cross_count} פעמים "
                f"ב-{self.chop_lookback} הנרות האחרונים) — מדלג על הכניסה."
            )
            signal = Signal(action="NONE", reason=thought)
        else:
            # The slow EMA lags behind on purpose, so right after a decline
            # turns into a recovery (or a rally into a pullback) the fast EMA
            # already flips direction while the slow one is still catching
            # up — bias stays on the old side for a bit even though price
            # itself is visibly moving the other way. Saying "trending down"
            # in that moment reads as flat wrong against the chart, so call
            # out the recovery/pullback explicitly instead of asserting a
            # trend direction the price action no longer supports.
            fast_rising = fast_now > fast_prev
            if bias == "BUY":
                thought = (
                    "המחיר נוטה לעלייה, ממתין לרגע הנכון להיכנס (לקניה)."
                    if fast_rising
                    else "המחיר נסוג קצת אחרי העלייה, עדיין מעל הממוצע האיטי — ממתין לחצייה למטה שתאשר מכירה, או שהעלייה תתחדש."
                )
            else:
                thought = (
                    "המחיר נוטה לירידה, ממתין לרגע הנכון להיכנס (למכירה)."
                    if not fast_rising
                    else "המחיר מתאושש אחרי הירידה, אבל עדיין מתחת לממוצע האיטי — ממתין לחצייה למעלה שתאשר קנייה, או שהירידה תתחדש."
                )
            signal = Signal(action="NONE", reason=thought)

        return EvaluationResult(thought=thought, signal=signal, indicators=indicators, bias=bias)
