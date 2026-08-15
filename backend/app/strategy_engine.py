"""Runs the active strategy on every closed candle for its configured granularity,
persists the resulting thought, and broadcasts it to the frontend. A non-NONE
signal is handed to OrderService, which decides (kill switch, risk limits,
feedback rules) whether it actually becomes a trade.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from app.broker.base import BrokerAdapter, Candle
from app.db import get_session
from app.indicators import ema
from app.market_data.aggregator import GRANULARITY_SECONDS
from app.models import ThoughtLog
from app.order_service import OrderService
from app.settings_store import trip_auto_stop
from app.strategies.base import Strategy
from app.strategies.utils import candles_to_dataframe
from app.timeutil import to_epoch
from app.ws.manager import ConnectionManager

logger = logging.getLogger(__name__)


class StrategyEngine:
    def __init__(
        self,
        strategy: Strategy,
        broker: BrokerAdapter,
        instrument: str,
        granularity: str,
        ws_manager: ConnectionManager,
        order_service: Optional[OrderService] = None,
        history_size: int = 200,
    ):
        self._strategy = strategy
        self._broker = broker
        self._instrument = instrument
        self._granularity = granularity
        self._ws = ws_manager
        self._order_service = order_service
        self._history_size = history_size
        self._candles: deque[Candle] = deque(maxlen=history_size)

    @property
    def active_strategy_id(self) -> str:
        return self._strategy.id

    def set_strategy(self, strategy: Strategy) -> None:
        # Candle history (plain OHLC) stays valid across a strategy switch — only
        # the evaluation logic changes. In-flight open trades stay tagged with the
        # strategy_id they were opened under (see Trade.strategy_id), so switching
        # here doesn't retroactively reinterpret them.
        self._strategy = strategy
        logger.info("Active strategy switched to %s", strategy.id)

    async def start(self) -> None:
        history = await self._fetch_fresh_history()
        self._candles.extend(history)
        logger.info(
            "StrategyEngine started | strategy=%s | granularity=%s | seeded %d candles",
            self._strategy.id,
            self._granularity,
            len(self._candles),
        )

    async def _fetch_fresh_history(self, max_attempts: int = 5, retry_delay_seconds: float = 1.0) -> list[Candle]:
        """Right after a (re)connect, MT5's terminal can still be syncing its
        local price-history cache for the symbol — a history request made too
        soon can come back with its newest bar minutes (even hours) stale
        instead of truly current, which silently poisons every EMA computed
        off this seed until enough fresh live candles displace it (a span=50
        EMA needs on the order of 100+ new bars to fully recover — discovered
        via a real ema50 misread on the live account after one such restart).
        Retry a few times with a short pause if the freshest bar we get back
        isn't actually recent.
        """
        interval_seconds = GRANULARITY_SECONDS.get(self._granularity, 60)
        history: list[Candle] = []
        for attempt in range(1, max_attempts + 1):
            history = await self._broker.get_candles(self._instrument, self._granularity, count=self._history_size)
            if history:
                age_seconds = (datetime.now(timezone.utc) - history[-1].time).total_seconds()
                if age_seconds <= interval_seconds * 3:
                    return history
                logger.warning(
                    "Seeded candle history looks stale (latest bar %.0f min old) — retrying (%d/%d)",
                    age_seconds / 60,
                    attempt,
                    max_attempts,
                )
            await asyncio.sleep(retry_delay_seconds)

        # Still stale after every retry — refuse to trade on it rather than risk
        # repeating the ema50 misread this guard exists for: trip the kill switch
        # and tell the frontend exactly why, instead of silently proceeding on
        # data we already know we can't trust.
        stale_minutes = (
            round((datetime.now(timezone.utc) - history[-1].time).total_seconds() / 60) if history else None
        )
        trip_auto_stop(
            f"הבוט נעצר אוטומטית: הנתונים ההיסטוריים מ-MT5 היו לא עדכניים "
            f"({stale_minutes if stale_minutes is not None else '?'} דקות ישנים) ולא ניתן היה לחשב אינדיקטורים "
            "אמינים. יש לוודא שהנתונים תקינים ולהפעיל מחדש ידנית בהגדרות."
        )
        logger.warning(
            "Candle history still stale after %d attempts (latest bar %s min old) — bot auto-disabled, refusing to trade blind",
            max_attempts,
            stale_minutes,
        )
        await self._ws.broadcast(
            {
                "type": "bot_status",
                "payload": {
                    "bot_enabled": False,
                    "auto_stopped_reason": "stale_history",
                    "stale_minutes": stale_minutes,
                },
            }
        )
        return history

    async def on_candle_closed(self, granularity: str, candle: Candle) -> None:
        if granularity != self._granularity:
            return

        self._candles.append(candle)
        if len(self._candles) < self._strategy.required_history():
            return

        df = candles_to_dataframe(self._candles)
        result = self._strategy.evaluate(df)

        # Universal trend reading, added regardless of whether the active
        # strategy computes its own EMA-50 — OrderService.handle_signal uses
        # it to enforce "only trade with the higher-timeframe trend" the same
        # way no matter which strategy is running.
        result.indicators["ema50"] = round(float(ema(df["close"], 50).iloc[-1]), 2)

        with get_session() as session:
            row = ThoughtLog(
                strategy_id=self._strategy.id,
                candle_time=candle.time,
                text=result.thought,
                signal=result.signal.action,
                indicators_json=json.dumps(result.indicators),
                instrument=self._instrument,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            thought_id = row.id
            timestamp = row.timestamp

        await self._ws.broadcast(
            {
                "type": "thought",
                "payload": {
                    "id": thought_id,
                    "time": to_epoch(timestamp),
                    "candle_time": int(candle.time.timestamp()),
                    "text": result.thought,
                    "signal": result.signal.action,
                    "indicators": result.indicators,
                    "bias": result.bias,
                    "instrument": self._instrument,
                },
            }
        )

        if result.signal.action != "NONE" and self._order_service is not None:
            await self._order_service.handle_signal(result.signal, self._strategy.id, candle, result.indicators)
