"""No-broker-account gold data source: Twelve Data's public REST API. Chosen as
the OANDA alternative when a broker account isn't available (e.g. region-blocked) —
Twelve Data has no account/KYC requirement, just an API key.

The free "Basic" plan caps usage at 8 requests/minute AND 800 requests/day —
the daily cap is the binding one if the app stays open for a full day, so the
poll interval below is sized off that (not the per-minute cap). Still a large
improvement over Yahoo Finance's free futures data, which runs ~10 minutes
delayed regardless of poll frequency.

Read-only: `place_order` / `close_position` / `get_account_state` raise
NotImplementedError, same as the Yahoo adapter — trading always goes through the
internal SimulatedBrokerAdapter regardless of data source (see order_service.py).
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

_SYMBOL = "XAU/USD"
_BASE_URL = "https://api.twelvedata.com"

# 800 requests/day ÷ 1440 minutes/day leaves ~0.55 req/min if polled 24/7; 90s
# (=960 req/day) already overshoots that, so we go wider still to leave real
# margin for backfill calls (each timeframe switch costs one time_series call).
_POLL_INTERVAL_SECONDS = 120

_GRANULARITY_TO_INTERVAL = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "H1": "1h",
}


def _parse_time_series_bars(body: dict) -> list[tuple[datetime, float, float, float, float]]:
    values = body.get("values") or []
    return [
        (
            datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
            float(v["open"]),
            float(v["high"]),
            float(v["low"]),
            float(v["close"]),
        )
        for v in values
    ]


class TwelveDataAdapter(BrokerAdapter):
    def __init__(self, api_key: str) -> None:
        if not api_key:
            logger.warning(
                "TwelveDataAdapter active but TWELVEDATA_API_KEY is empty — requests will fail. "
                "Get a free key at twelvedata.com and set it in backend/.env."
            )
        self._api_key = api_key
        logger.warning(
            "TwelveDataAdapter active — no-account gold data (%s), read-only, polled every %ss.",
            _SYMBOL,
            _POLL_INTERVAL_SECONDS,
        )

    async def get_candles(self, instrument: str, granularity: str, count: int = 500) -> list[Candle]:
        interval = _GRANULARITY_TO_INTERVAL.get(granularity, "1min")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_BASE_URL}/time_series",
                params={
                    "symbol": _SYMBOL,
                    "interval": interval,
                    "outputsize": min(count, 5000),
                    "timezone": "UTC",
                    "apikey": self._api_key,
                },
            )
            resp.raise_for_status()
            body = resp.json()

        if body.get("status") == "error":
            raise RuntimeError(f"Twelve Data error: {body.get('message', 'unknown error')}")

        bars = _parse_time_series_bars(body)
        candles = [
            Candle(time=t, open=o, high=h, low=l, close=c, complete=True) for t, o, h, l, c in bars
        ]
        candles.reverse()  # Twelve Data returns newest-first
        return candles[-count:]

    async def stream_prices(self, instrument: str) -> AsyncIterator[PriceTick]:
        # Polls the same real 1-min bars used for backfill (rather than the crude
        # /price endpoint) and replays each bar's true open/high/low/close as four
        # ticks. A single last-traded-price poll every 120s would otherwise turn
        # each locally-built candle into one flat point — degenerate O=H=L=C, with
        # most real 1-min buckets skipped entirely between polls — which both looks
        # broken on the chart and (more seriously) lets SL/TP checks miss real
        # intraminute price crossings that never happened to land on a poll instant.
        #
        # `last_emitted_time` guards against replaying an already-finalized older
        # bar as if it were a new one (which would look like a bucket transition
        # to CandleAggregator and wrongly close out the in-progress candle) — we
        # only skip bars strictly older than the newest one already emitted, so
        # the still-forming latest bar keeps updating in place each poll, and any
        # newly-completed bars in between get replayed in order.
        last_emitted_time: datetime | None = None
        async with httpx.AsyncClient(timeout=15) as client:
            while True:
                try:
                    resp = await client.get(
                        f"{_BASE_URL}/time_series",
                        params={
                            "symbol": _SYMBOL,
                            "interval": "1min",
                            "outputsize": 5,
                            "timezone": "UTC",
                            "apikey": self._api_key,
                        },
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    if body.get("status") == "error":
                        logger.warning("Twelve Data time_series poll error: %s", body.get("message"))
                    else:
                        bars = _parse_time_series_bars(body)
                        bars.sort(key=lambda b: b[0])  # oldest first
                        for bar_time, o, h, l, c in bars:
                            if last_emitted_time is not None and bar_time < last_emitted_time:
                                continue
                            for price in (o, h, l, c):
                                yield PriceTick(instrument=instrument, time=bar_time, bid=price, ask=price)
                            last_emitted_time = bar_time
                except Exception:
                    logger.exception("Twelve Data poll failed, retrying in %ss", _POLL_INTERVAL_SECONDS)
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def place_order(
        self,
        instrument: str,
        side: Side,
        units: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResult:
        raise NotImplementedError(
            "TwelveDataAdapter is data-only — trading goes through the internal simulated broker."
        )

    async def close_position(self, trade_id: str) -> OrderResult:
        raise NotImplementedError(
            "TwelveDataAdapter is data-only — trading goes through the internal simulated broker."
        )

    async def get_open_trades(self) -> list[BrokerTrade]:
        return []

    async def get_account_state(self) -> AccountState:
        raise NotImplementedError("TwelveDataAdapter is data-only — no account state to report.")
