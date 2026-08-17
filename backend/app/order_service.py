"""Turns strategy signals into trades (simulated by default, or real orders on
a live broker when `live=True` — see EXECUTION_MODE), persists them, and
enforces the kill switch + basic risk limits + active feedback rules before any
order is placed. This is the ONE place that decides whether a signal actually
becomes a trade — the strategy engine only proposes, it never executes directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.broker.base import Candle
from app.broker.simulated import SimulatedBrokerAdapter
from app.db import get_session
from app.feedback_rules import evaluate_feedback_rules
from app.instruments import instrument_label
from app.models import FeedbackRule, Trade
from app.notify.telegram import send_telegram_message
from app.settings_store import get_setting, is_bot_enabled, set_setting, trip_auto_stop
from app.strategies.base import Signal
from app.timeutil import as_utc, to_epoch, trading_day_str
from app.trade_stats import todays_realized_pnl
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
        breakeven_extend_rr: float = 4.0,
        trade_cooldown_minutes: float = 15.0,
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
        # How far (in multiples of the ORIGINAL risk) the target gets pushed
        # out once price reaches it — see _check_breakeven_extension.
        self._breakeven_extend_rr = breakeven_extend_rr
        # Minimum gap after a trade CLOSES before a new one can open — see
        # the cooldown check in handle_signal.
        self._trade_cooldown_minutes = trade_cooldown_minutes
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
        # Before checking for closes, so a trade that just reached its
        # original target gets its stop/target moved out first instead of
        # closing at the now-obsolete take-profit this same candle.
        await self._check_breakeven_extension(candle)
        await self._check_halfway_breakeven(candle)
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

    async def _check_breakeven_extension(self, candle: Candle) -> None:
        """Once price reaches a trade's *original* take-profit, don't bank it
        there — move the stop to breakeven and push the target out to
        `breakeven_extend_rr` times the original risk instead, so a move that
        keeps running past the old target isn't cut short. Works for both the
        simulated broker and a real one (modify_position_manually already
        knows how to reach each). Runs at most once per trade, tracked via
        `target_extended` (NOT stop position — the halfway-to-target rule can
        also move the stop to breakeven earlier, on its own, without this
        having run yet).
        """
        with get_session() as session:
            candidates = [
                (t.id, t.side, t.entry_price, t.stop_loss, t.take_profit, t.initial_risk)
                for t in session.exec(select(Trade).where(Trade.status == "OPEN")).all()
                if t.stop_loss is not None and t.take_profit is not None and not t.target_extended
            ]

        for trade_id, side, entry, stop_loss, take_profit, initial_risk in candidates:
            direction = 1 if side == "BUY" else -1
            reached_original_target = candle.high >= take_profit if side == "BUY" else candle.low <= take_profit
            if not reached_original_target:
                continue

            # Conservative tie-break matching SimulatedBrokerAdapter.check_stop_loss_take_profit:
            # if this same (wide) candle's range would have also hit the CURRENT stop, treat
            # that as having happened — don't extend a trade past a stop it already would have
            # been closed at, since a single-candle range can't tell us which came first.
            hit_current_stop = candle.low <= stop_loss if side == "BUY" else candle.high >= stop_loss
            if hit_current_stop:
                continue

            # Prefer the risk captured at open time — by now stop_loss may already
            # sit at breakeven (moved there by _check_halfway_breakeven), which would
            # make abs(entry - stop_loss) read as ~0 instead of the real original risk.
            risk = initial_risk if initial_risk else abs(entry - stop_loss)
            if risk <= 0:
                continue
            new_take_profit = entry + direction * self._breakeven_extend_rr * risk
            ok = await self.modify_position_manually(trade_id, entry, new_take_profit)
            if ok:
                with get_session() as session:
                    trade = session.get(Trade, trade_id)
                    if trade is not None:
                        trade.target_extended = True
                        session.add(trade)
                        session.commit()
                logger.info(
                    "Trade %d reached its original target (%.2f) — moved stop to breakeven (%.2f) and extended target to %.2f",
                    trade_id,
                    take_profit,
                    entry,
                    new_take_profit,
                )

    async def _check_halfway_breakeven(self, candle: Candle) -> None:
        """Once price has covered half the distance from entry to the
        *original* take-profit, move the stop to entry (breakeven) so the
        trade can no longer end at a loss — the target itself is left
        untouched here (see _check_breakeven_extension for what happens once
        it reaches the full target). Runs at most once per trade: a stop
        already sitting at or past entry — whether moved here or by the full
        extension above — is how "already done" is recognized.
        """
        with get_session() as session:
            candidates = [
                (t.id, t.side, t.entry_price, t.stop_loss, t.take_profit)
                for t in session.exec(select(Trade).where(Trade.status == "OPEN")).all()
                if t.stop_loss is not None and t.take_profit is not None
            ]

        for trade_id, side, entry, stop_loss, take_profit in candidates:
            direction = 1 if side == "BUY" else -1
            if (stop_loss - entry) * direction >= -1e-9:
                continue  # stop already at/past breakeven

            # Same conservative tie-break as the full extension: don't move the
            # stop to "safety" if this candle's range could just as well have
            # hit the original stop first.
            hit_original_stop = candle.low <= stop_loss if side == "BUY" else candle.high >= stop_loss
            if hit_original_stop:
                continue

            halfway = entry + direction * (take_profit - entry) / 2
            reached_halfway = candle.high >= halfway if side == "BUY" else candle.low <= halfway
            if not reached_halfway:
                continue

            ok = await self.modify_position_manually(trade_id, entry, None)
            if ok:
                logger.info(
                    "Trade %d reached halfway to its target (%.2f) — moved stop to breakeven (%.2f), no more downside risk",
                    trade_id,
                    halfway,
                    entry,
                )

    async def handle_signal(self, signal: Signal, strategy_id: str, candle: Candle, indicators: dict) -> None:
        if signal.action not in ("BUY", "SELL"):
            return

        if not is_bot_enabled():
            logger.info("Signal %s ignored — bot is disabled (kill switch)", signal.action)
            return

        if self._trade_cooldown_minutes > 0:
            with get_session() as session:
                last_closed = session.exec(
                    select(Trade).where(Trade.status == "CLOSED").order_by(Trade.exit_time.desc())
                ).first()
            if last_closed is not None and last_closed.exit_time is not None:
                elapsed = candle.time - as_utc(last_closed.exit_time)
                cooldown = timedelta(minutes=self._trade_cooldown_minutes)
                if elapsed < cooldown:
                    remaining_min = (cooldown - elapsed).total_seconds() / 60
                    logger.info("Signal %s ignored — trade cooldown active, %.1f more minutes", signal.action, remaining_min)
                    await self._ws.broadcast(
                        {
                            "type": "bot_status",
                            "payload": {
                                "blocked_signal": signal.action,
                                "rule": f"קירור אחרי עסקה — עוד כ-{remaining_min:.0f} דקות",
                            },
                        }
                    )
                    return

        direction_bias = get_setting("chat_direction_bias")
        if direction_bias and signal.action != direction_bias:
            wanted = "קנייה" if direction_bias == "BUY" else "מכירה"
            logger.info("Signal %s ignored — chat direction bias waiting for %s", signal.action, direction_bias)
            await self._ws.broadcast(
                {
                    "type": "bot_status",
                    "payload": {"blocked_signal": signal.action, "rule": f"הנחיית צ'אט: ממתין לאיתות {wanted}"},
                }
            )
            return

        ema50 = indicators.get("ema50")
        if ema50 is not None:
            price = candle.close
            if price > ema50 and signal.action == "SELL":
                logger.info("Signal SELL ignored — price above EMA50 (%.2f > %.2f), only BUY allowed", price, ema50)
                await self._ws.broadcast(
                    {
                        "type": "bot_status",
                        "payload": {
                            "blocked_signal": "SELL",
                            "rule": f"מחיר מעל EMA50 ({ema50:.2f}) — מותרות רק עסקאות קנייה",
                        },
                    }
                )
                return
            if price < ema50 and signal.action == "BUY":
                logger.info("Signal BUY ignored — price below EMA50 (%.2f < %.2f), only SELL allowed", price, ema50)
                await self._ws.broadcast(
                    {
                        "type": "bot_status",
                        "payload": {
                            "blocked_signal": "BUY",
                            "rule": f"מחיר מתחת ל-EMA50 ({ema50:.2f}) — מותרות רק עסקאות מכירה",
                        },
                    }
                )
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

        units = await self._position_size(candle.close, stop_loss)
        result = await self._broker.place_order(self._instrument, signal.action, units, stop_loss, take_profit)
        if not result.success:
            logger.warning("Order placement failed: %s", result.message)
            return

        entry_price = result.fill_price or 0.0
        with get_session() as session:
            trade = Trade(
                broker_trade_id=result.broker_trade_id,
                instrument=self._instrument,
                side=signal.action,
                status="OPEN",
                entry_price=entry_price,
                entry_time=candle.time,
                stop_loss=stop_loss,
                take_profit=take_profit,
                units=units,
                strategy_id=strategy_id,
                signal_reason=signal.reason,
                initial_risk=abs(entry_price - stop_loss),
            )
            session.add(trade)
            session.commit()
            session.refresh(trade)
            payload = _trade_dict(trade)

        await self._ws.broadcast({"type": "trade_opened", "payload": payload})
        await send_telegram_message(f"🟢 נפתחה עסקה ב{instrument_label(payload['instrument'])}")

        if direction_bias and signal.action == direction_bias:
            set_setting("chat_direction_bias", "")
            await self._ws.broadcast({"type": "bot_status", "payload": {"direction_bias": None}})

    async def _position_size(self, price: float, stop_loss: float) -> float:
        """Risk-based sizing: units such that a stop-out loses exactly the
        target $ risk — (price - stop_loss) * units is the $ risk regardless
        of contract size, since `units` here is the same notional quantity
        the broker later divides by its own contract size (see
        MT5Adapter._units_to_volume). Priority: a fixed `risk_dollars` amount
        (if set) wins over `risk_pct` of the current balance, which wins over
        the flat `risk_units` fallback — used whenever both are 0/disabled or
        the stop distance/balance can't be read, so this never silently
        blocks a trade.
        """
        stop_distance = abs(price - stop_loss)
        if stop_distance > 0:
            risk_dollars = float(get_setting("risk_dollars"))
            if risk_dollars > 0:
                return risk_dollars / stop_distance

            risk_pct = float(get_setting("risk_pct"))
            if risk_pct > 0:
                try:
                    account = await self._broker.get_account_state()
                    return (account.balance * risk_pct / 100) / stop_distance
                except Exception:
                    logger.warning("Could not read account balance for risk-based sizing, falling back to risk_units", exc_info=True)
        return float(get_setting("risk_units"))

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

        pnl = payload["pnl"] or 0.0
        emoji = "✅" if pnl >= 0 else "❌"
        result_label = "רווח" if pnl >= 0 else "הפסד"
        await send_telegram_message(f"{emoji} נסגרה עסקה ב{result_label} של {abs(pnl):.2f}")

        await self._check_daily_profit_stop()

    async def _check_daily_profit_stop(self) -> None:
        """Optional risk guard: once today's realized PnL reaches
        `daily_profit_target_pct` of the balance the trading day started with,
        trip the kill switch until the next trading day starts (the next
        London session open, 08:00 UTC — settings_store auto-clears the switch
        then, see reset_daily_stop_if_new_day). Realized PnL only, same basis
        as the portfolio stats page — floating PnL on still-open positions
        doesn't count until it's actually closed.
        """
        try:
            target_pct = float(get_setting("daily_profit_target_pct"))
        except ValueError:
            target_pct = 0.0
        if target_pct <= 0 or not is_bot_enabled():
            return

        todays_pnl = todays_realized_pnl()
        if todays_pnl <= 0:
            return

        account = await self._broker.get_account_state()
        baseline_balance = account.balance - todays_pnl  # balance the trading day started with
        if baseline_balance <= 0:
            return
        todays_pnl_pct = todays_pnl / baseline_balance * 100
        if todays_pnl_pct < target_pct:
            return

        set_setting("daily_stop_date", trading_day_str())
        trip_auto_stop(f"הבוט הגיע ליעד הרווח היומי ({todays_pnl_pct:.2f}%) ונעצר אוטומטית עד מחר")
        logger.warning(
            "Daily profit target reached (%.2f%% >= %.2f%%) — bot auto-disabled until the next trading day (08:00 UTC)",
            todays_pnl_pct,
            target_pct,
        )
        await self._ws.broadcast(
            {
                "type": "bot_status",
                "payload": {"bot_enabled": False, "auto_stopped_reason": "daily_profit_target", "pnl_pct": round(todays_pnl_pct, 2)},
            }
        )

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
