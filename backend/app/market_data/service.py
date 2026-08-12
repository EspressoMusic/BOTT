"""Owns the background task that consumes the broker's live price stream,
feeds it through the CandleAggregator, and broadcasts candle events over WebSocket.

Reconnects with exponential backoff on stream errors — a bot that goes silently
blind to price while still "enabled" is a real risk, so failures are logged loudly
rather than swallowed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.broker.base import BrokerAdapter, Candle
from app.market_data.aggregator import GRANULARITY_SECONDS, CandleAggregator
from app.ws.manager import ConnectionManager

OnCandleClosed = Callable[[str, Candle], Awaitable[None]]

logger = logging.getLogger(__name__)

_MAX_BACKOFF_SECONDS = 30


def _candle_to_dict(candle: Candle) -> dict:
    return {
        "time": int(candle.time.timestamp()),
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
    }


class MarketDataService:
    def __init__(
        self,
        broker: BrokerAdapter,
        instrument: str,
        ws_manager: ConnectionManager,
        on_candle_closed: OnCandleClosed | None = None,
    ):
        self._broker = broker
        self._instrument = instrument
        self._ws = ws_manager
        self._on_candle_closed = on_candle_closed
        self._aggregator = CandleAggregator(list(GRANULARITY_SECONDS))
        self._task: asyncio.Task | None = None
        self._stop = False

    def start(self) -> None:
        self._stop = False
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        backoff = 1
        while not self._stop:
            try:
                logger.info("Connecting to OANDA price stream for %s", self._instrument)
                async for tick in self._broker.stream_prices(self._instrument):
                    backoff = 1
                    for event in self._aggregator.apply_tick(tick):
                        await self._ws.broadcast(
                            {
                                "type": "candle_closed" if event.closed else "candle_update",
                                "payload": {
                                    "granularity": event.granularity,
                                    "candle": _candle_to_dict(event.candle),
                                },
                            }
                        )
                        if event.closed and self._on_candle_closed is not None:
                            try:
                                await self._on_candle_closed(event.granularity, event.candle)
                            except Exception:
                                logger.exception("on_candle_closed callback failed, continuing stream")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Price stream error — reconnecting in %ss", backoff)
                await self._ws.broadcast({"type": "bot_status", "payload": {"stream": "reconnecting"}})
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)
