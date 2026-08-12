"""Turns strategy signals into trades (simulated by default, or real orders on
a live broker when `live=True` — see EXECUTION_MODE), persists them, and
enforces the kill switch + basic risk limits + active feedback rules before any
order is placed. This is the ONE place that decides whether a signal actually
becomes a trade — the strategy engine only proposes, it never executes directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import select

from app.broker.base import Candle
from app.broker.simulated import SimulatedBrokerAdapter
from app.db import get_session
from app.feedback_rules import evaluate_feedback_rules
from app.models import FeedbackRule, Trade
from app.settings_store import get_setting, is_bot_enabled
from app.strategies.base import Signal
from app.timeutil import to_epoch
from app.ws.manager import ConnectionManager

logger = logging.getLogger(__name__)


def _trade_dict(trade: Trade) -> dict:
    return {
        "id": trade.id,
        "instrument": trade.instrument,
        "side": trade.side,
        "status": trade.status,
        "entry_price": trade.entry_price,
        "entry_time": to_epoch(trade.entry_time),
        "exit_price": trade.exit_price,
        "exit_time": to_epoch(trade.exit_time) if trade.exit_time else None,
        "exit_reason": trade.exit_reason,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "units": trade.units,
        "pnl": trade.pnl,
        "strategy_id": trade.strategy_id,
        "signal_reason": trade.signal_reason,
    }


class OrderService:
    def __init__(
        self,
        broker: SimulatedBrokerAdapter,
        ws_manager: ConnectionManager,
        instrument: str,
        granularity: str,
        default_stop_distance: float = 15.0,
        default_target_distance: float = 30.0,
        live: bool = False,
    ):
        self._broker = broker
        self._ws = ws_manager
        self._instrument = instrument
        self._granularity = granularity
        # Applied only when a strategy's signal doesn't compute its own SL/TP
        # (e.g. the ATR strategy sets its own, sized to current volatility) —
        # every trade gets a protective stop either way.
        self._default_stop_distance = default_stop_distance
        self._default_target_distance = default_target_distance
        # True when `broker` is a real adapter (OANDA/MT5) placing real orders,
        # as opposed to the in-process SimulatedBrokerAdapter. A real broker
        # manages SL/TP itself server-side and has no update_price/
        # check_stop_loss_take_profit methods, so closes are detected instead by
        # reconciling our DB's OPEN trades against the broker's actual open
        # positions — see `_reconcile_live`.
        self._live = live

    async def on_candle_closed(self, granularity: str, candle: Candle) -> None:
        # Only the finest tracked granularity — checking SL/TP against a coarser
        # candle's wider [low, high] range would trigger exits too eagerly.
        if granularity != self._granularity:
            return
        if self._live:
            await self._reconcile_live(candle)
            return
        self._broker.update_price(candle.close)
        for pos, exit_price, reason in self._broker.check_stop_loss_take_profit(candle.low, candle.high):
            await self._record_close(pos.id, exit_price, reason, candle.time)

    async def _reconcile_live(self, candle: Candle) -> None:
        """Real brokers apply SL/TP server-side, so a trade that's OPEN in our
        DB can have already been closed at the broker without us placing the
        close ourselves (SL/TP hit, or the position was closed by hand in the
        broker's own terminal/app). Detect that by diffing our OPEN trades
        against the broker's actual open positions, and infer the exit price
        and reason from whichever stored SL/TP level this candle's range
        crossed — falling back to "MANUAL" when neither was crossed (closed
        at the broker outside our own tracking)."""
        with get_session() as session:
            open_trades = session.exec(select(Trade).where(Trade.status == "OPEN")).all()
            open_trades = [(t.broker_trade_id, t.side, t.stop_loss, t.take_profit) for t in open_trades]
        if not open_trades:
            return

        broker_open_ids = {t.broker_trade_id for t in await self._broker.get_open_trades()}

        for broker_trade_id, side, stop_loss, take_profit in open_trades:
            if broker_trade_id in broker_open_ids:
                continue  # still open at the broker

            exit_price, reason = candle.close, "MANUAL"
            if side == "BUY":
                if stop_loss is not None and candle.low <= stop_loss:
                    exit_price, reason = stop_loss, "SL"
                elif take_profit is not None and candle.high >= take_profit:
                    exit_price, reason = take_profit, "TP"
            else:
                if stop_loss is not None and candle.high >= stop_loss:
                    exit_price, reason = stop_loss, "SL"
                elif take_profit is not None and candle.low <= take_profit:
                    exit_price, reason = take_profit, "TP"
            await self._record_close(broker_trade_id, exit_price, reason, candle.time)

    async def handle_signal(self, signal: Signal, strategy_id: str, candle: Candle, indicators: dict) -> None:
        if signal.action not in ("BUY", "SELL"):
            return

        if not is_bot_enabled():
            logger.info("Signal %s ignored — bot is disabled (kill switch)", signal.action)
            return

        max_positions = int(get_setting("max_concurrent_positions"))
        if len(await self._broker.get_open_trades()) >= max_positions:
            logger.info("Signal %s ignored — max concurrent positions (%d) reached", signal.action, max_positions)
            return

        blocked_by = evaluate_feedback_rules(signal.action, indicators)
        if blocked_by is not None:
            logger.info("Signal %s blocked by feedback rule: %s", signal.action, blocked_by.description)
            await self._ws.broadcast(
                {
                    "type": "bot_status",
                    "payload": {"blocked_signal": signal.action, "rule": blocked_by.description},
                }
            )
            return

        direction = 1 if signal.action == "BUY" else -1
        stop_loss = signal.stop_loss if signal.stop_loss is not None else candle.close - direction * self._default_stop_distance
        take_profit = (
            signal.take_profit if signal.take_profit is not None else candle.close + direction * self._default_target_distance
        )

        units = int(get_setting("risk_units"))
        result = await self._broker.place_order(self._instrument, signal.action, units, stop_loss, take_profit)
        if not result.success:
            logger.warning("Order placement failed: %s", result.message)
            return

        with get_session() as session:
            trade = Trade(
                broker_trade_id=result.broker_trade_id,
                instrument=self._instrument,
                side=signal.action,
                status="OPEN",
                entry_price=result.fill_price or 0.0,
                entry_time=candle.time,
                stop_loss=stop_loss,
                take_profit=take_profit,
                units=units,
                strategy_id=strategy_id,
                signal_reason=signal.reason,
            )
            session.add(trade)
            session.commit()
            session.refresh(trade)
            payload = _trade_dict(trade)

        await self._ws.broadcast({"type": "trade_opened", "payload": payload})

    async def _record_close(self, broker_trade_id: str, exit_price: float, reason: str, exit_time: datetime) -> None:
        with get_session() as session:
            trade = session.exec(
                select(Trade).where(Trade.broker_trade_id == broker_trade_id, Trade.status == "OPEN")
            ).first()
            if trade is None:
                return
            direction = 1 if trade.side == "BUY" else -1
            trade.status = "CLOSED"
            trade.exit_price = exit_price
            trade.exit_time = exit_time
            trade.exit_reason = reason
            trade.pnl = (exit_price - trade.entry_price) * direction * trade.units
            session.add(trade)
            session.commit()
            session.refresh(trade)
            payload = _trade_dict(trade)

        await self._ws.broadcast({"type": "trade_closed", "payload": payload})

    async def modify_position_manually(
        self, trade_db_id: int, stop_loss: float | None, take_profit: float | None
    ) -> bool:
        with get_session() as session:
            trade = session.get(Trade, trade_db_id)
            if trade is None or trade.status != "OPEN" or trade.broker_trade_id is None:
                return False
            if self._live:
                ok = await self._broker.modify_position(trade.broker_trade_id, stop_loss, take_profit)
            else:
                ok = self._broker.modify_position(trade.broker_trade_id, stop_loss, take_profit)
            if not ok:
                return False
            if stop_loss is not None:
                trade.stop_loss = stop_loss
            if take_profit is not None:
                trade.take_profit = take_profit
            session.add(trade)
            session.commit()
            session.refresh(trade)
            payload = _trade_dict(trade)

        await self._ws.broadcast({"type": "trade_modified", "payload": payload})
        return True

    async def close_position_manually(self, trade_db_id: int) -> bool:
        with get_session() as session:
            trade = session.get(Trade, trade_db_id)
            if trade is None or trade.status != "OPEN" or trade.broker_trade_id is None:
                return False
            broker_trade_id = trade.broker_trade_id

        result = await self._broker.close_position(broker_trade_id)
        if not result.success or result.fill_price is None:
            return False

        await self._record_close(broker_trade_id, result.fill_price, "MANUAL", datetime.now(timezone.utc))
        return True
