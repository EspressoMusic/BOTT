"""Runs the active strategy on every closed candle for its configured granularity,
persists the resulting thought, and broadcasts it to the frontend. A non-NONE
signal is handed to OrderService, which decides (kill switch, risk limits,
feedback rules) whether it actually becomes a trade.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from typing import Optional

from app.broker.base import BrokerAdapter, Candle
from app.db import get_session
from app.models import ThoughtLog
from app.order_service import OrderService
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
        history = await self._broker.get_candles(self._instrument, self._granularity, count=self._history_size)
        self._candles.extend(history)
        logger.info(
            "StrategyEngine started | strategy=%s | granularity=%s | seeded %d candles",
            self._strategy.id,
            self._granularity,
            len(self._candles),
        )

    async def on_candle_closed(self, granularity: str, candle: Candle) -> None:
        if granularity != self._granularity:
            return

        self._candles.append(candle)
        if len(self._candles) < self._strategy.required_history():
            return

        df = candles_to_dataframe(self._candles)
        result = self._strategy.evaluate(df)

        with get_session() as session:
            row = ThoughtLog(
                strategy_id=self._strategy.id,
                candle_time=candle.time,
                text=result.thought,
                signal=result.signal.action,
                indicators_json=json.dumps(result.indicators),
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
                },
            }
        )

        if result.signal.action != "NONE" and self._order_service is not None:
            await self._order_service.handle_signal(result.signal, self._strategy.id, candle, result.indicators)
