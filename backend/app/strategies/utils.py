from collections.abc import Iterable

import pandas as pd

from app.broker.base import Candle


def candles_to_dataframe(candles: Iterable[Candle]) -> pd.DataFrame:
    candles = list(candles)
    return pd.DataFrame(
        {
            "time": [c.time for c in candles],
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
        }
    )
