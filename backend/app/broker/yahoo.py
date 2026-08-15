"""Temporary, no-signup gold data source: Yahoo Finance's public (unofficial)
chart API. Lets the live chart be demoed before an OANDA practice account exists.

Read-only: `place_order` / `close_position` / `get_account_state` raise
NotImplementedError, since Yahoo Finance has no trading/order API at all. Switch
DATA_SOURCE=oanda once real demo order placement is needed (Phase 2+).

Always tracks COMEX gold futures (GC=F) regardless of the `instrument` argument
passed in — this is a single-purpose gold stand-in, not a general multi-instrument
adapter. GC=F tracks spot XAU/USD closely (both are "the price of gold in USD"),
though it is not tick-identical to OANDA's XAU_USD.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import httpx

from app.broker.base import (
    AccountState,
    BrokerAdapter,
    BrokerTrade,
    Candle,
    OrderResult,
    PriceTick,
    Side,
)

logger = logging.getLogger(__name__)

_SYMBOL = "GC=F"
_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
_HEADERS = {"User-Agent": "Mozilla/5.0 (BOTT gold trading dashboard)"}
_POLL_INTERVAL_SECONDS = 5

# Yahoo restricts how far back each interval can go; pick a range comfortably
# within the limit for each granularity we support.
_GRANULARITY_TO_YAHOO = {
    "M1": ("1m", "5d"),
    "M5": ("5m", "60d"),
    "M15": ("15m", "60d"),
    "H1": ("60m", "730d"),
}


class YahooFinanceAdapter(BrokerAdapter):
    def __init__(self) -> None:
        logger.warning(
            "YahooFinanceAdapter active — no-signup gold FUTURES data (%s), read-only, "
            "polled every %ss (not true push streaming). Switch DATA_SOURCE=oanda for "
            "real demo order placement.",
            _SYMBOL,
            _POLL_INTERVAL_SECONDS,
        )

    async def get_candles(self, instrument: str, granularity: str, count: int = 500) -> list[Candle]:
        interval, yahoo_range = _GRANULARITY_TO_YAHOO.get(granularity, ("1m", "5d"))
        async with httpx.AsyncClient(headers=_HEADERS, timeout=15) as client:
            resp = await client.get(
                f"{_BASE_URL}/{_SYMBOL}",
                params={"interval": interval, "range": yahoo_range},
            )
            resp.raise_for_status()
            result = resp.json()["chart"]["result"][0]

        timestamps = result.get("timestamp") or []
        quote = result["indicators"]["quote"][0]

        candles: list[Candle] = []
        for i, ts in enumerate(timestamps):
            o, h, l, c = quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i]
            if None in (o, h, l, c):
                continue  # gaps (e.g. non-trading periods) come back as nulls
            candles.append(
                Candle(
                    time=datetime.fromtimestamp(ts, tz=timezone.utc),
                    open=float(o),
                    high=float(h),
                    low=float(l),
                    close=float(c),
                    complete=True,
                )
            )
        return candles[-count:]

    async def stream_prices(self, instrument: str) -> AsyncIterator[PriceTick]:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=15) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{_BASE_URL}/{_SYMBOL}",
                        params={"interval": "1m", "range": "1d"},
                    )
                    resp.raise_for_status()
                    meta = resp.json()["chart"]["result"][0]["meta"]
                    price = meta.get("regularMarketPrice")
                    if price is not None:
                        yield PriceTick(
                            instrument=instrument,
                            time=datetime.now(timezone.utc),
                            bid=float(price),
                            ask=float(price),
                        )
                except Exception:
                    logger.exception("Yahoo Finance poll failed, retrying in %ss", _POLL_INTERVAL_SECONDS)
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def place_order(
        self,
        instrument: str,
        side: Side,
        units: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResult:
        raise NotImplementedError(
            "YahooFinanceAdapter is data-only — set DATA_SOURCE=oanda to place orders."
        )

    async def close_position(self, trade_id: str) -> OrderResult:
        raise NotImplementedError(
            "YahooFinanceAdapter is data-only — set DATA_SOURCE=oanda to manage trades."
        )

    async def get_open_trades(self) -> list[BrokerTrade]:
        return []

    async def get_account_state(self) -> AccountState:
        raise NotImplementedError(
            "YahooFinanceAdapter is data-only — set DATA_SOURCE=oanda for account state."
        )
