"""Turns a stream of price ticks into OHLC candles per timeframe, in memory.

Pure logic, no I/O — kept separate from market_data/service.py so it can be
unit-tested as a plain function of (ticks in) -> (candle events out).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from app.broker.base import Candle, PriceTick

GRANULARITY_SECONDS: dict[str, int] = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "H1": 3600,
}


def bucket_start(time: datetime, granularity: str) -> datetime:
    seconds = GRANULARITY_SECONDS[granularity]
    epoch = int(time.timestamp())
    bucket_epoch = epoch - (epoch % seconds)
    return datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)


@dataclass
class CandleEvent:
    granularity: str
    candle: Candle
    closed: bool  # True = this candle just finished; False = still in progress


class CandleAggregator:
    """Maintains one in-progress candle per granularity and updates it from ticks."""

    def __init__(self, granularities: list[str] | None = None):
        self._granularities = granularities or list(GRANULARITY_SECONDS)
        self._current: dict[str, Candle] = {}

    def apply_tick(self, tick: PriceTick) -> list[CandleEvent]:
        events: list[CandleEvent] = []
        price = tick.mid

        for gran in self._granularities:
            start = bucket_start(tick.time, gran)
            current = self._current.get(gran)

            if current is None:
                new_candle = Candle(time=start, open=price, high=price, low=price, close=price, complete=False)
                self._current[gran] = new_candle
                events.append(CandleEvent(gran, replace(new_candle), closed=False))
                continue

            if current.time == start:
                current.high = max(current.high, price)
                current.low = min(current.low, price)
                current.close = price
                events.append(CandleEvent(gran, replace(current), closed=False))
                continue

            # tick crossed into a new bucket: close the old candle, open a new one
            current.complete = True
            events.append(CandleEvent(gran, replace(current), closed=True))
            new_candle = Candle(time=start, open=price, high=price, low=price, close=price, complete=False)
            self._current[gran] = new_candle
            events.append(CandleEvent(gran, replace(new_candle), closed=False))

        return events

    def get_current(self, granularity: str) -> Candle | None:
        return self._current.get(granularity)
