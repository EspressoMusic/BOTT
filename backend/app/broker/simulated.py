"""Paper-trading execution broker: no external account, no signup. Fills happen
instantly at whatever price the caller last reported via `update_price()`, and
SL/TP are checked against each closed candle's [low, high] range via
`check_stop_loss_take_profit()`.

This is execution-only — `get_candles`/`stream_prices` are never called on it in
practice (the app always uses a separate data-source broker, Yahoo or OANDA, for
the chart/strategy feed) and raise NotImplementedError if they ever are.

Deliberately concrete (not injected purely as an abstract BrokerAdapter) in
OrderService for now, since real-broker execution (OANDA) is a later step —
see plan notes on avoiding premature generalization.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional

from app.broker.base import (
    AccountState,
    BrokerAdapter,
    BrokerTrade,
    Candle,
    OrderResult,
    PriceTick,
    Side,
)


@dataclass
class SimPosition:
    id: str
    instrument: str
    side: Side
    units: int
    entry_price: float
    stop_loss: Optional[float]
    take_profit: Optional[float]


class SimulatedBrokerAdapter(BrokerAdapter):
    def __init__(self, starting_balance: float = 100_000.0):
        self._starting_balance = starting_balance
        self._last_price: Optional[float] = None
        self._positions: dict[str, SimPosition] = {}
        self._realized_pnl_total = 0.0
        self._next_id = 1

    def update_price(self, price: float) -> None:
        self._last_price = price

    def seed_open_positions(self, positions: list[SimPosition]) -> None:
        """Restore the in-memory position book from the DB's OPEN trades on
        startup. Without this, every backend restart forgets whatever was
        open (the position only ever lived in this process's memory), so it
        silently stops receiving SL/TP checks and no longer counts against
        max_concurrent_positions — while a brand new, unrelated trade opens
        right next to it. Also advances `_next_id` past any restored id so a
        freshly assigned id can never collide with (and overwrite the wrong
        DB row for) a restored one.
        """
        for pos in positions:
            self._positions[pos.id] = pos
        numeric_ids = [int(pos.id) for pos in positions if pos.id.isdigit()]
        if numeric_ids:
            self._next_id = max(self._next_id, max(numeric_ids) + 1)

    def check_stop_loss_take_profit(self, low: float, high: float) -> list[tuple[SimPosition, float, str]]:
        """Call once per closed candle. Returns (position, exit_price, reason) for
        every position whose SL/TP fell within this candle's range."""
        triggered: list[tuple[SimPosition, float, str]] = []
        for pos in list(self._positions.values()):
            hit: tuple[float, str] | None = None
            if pos.side == "BUY":
                if pos.stop_loss is not None and low <= pos.stop_loss:
                    hit = (pos.stop_loss, "SL")
                elif pos.take_profit is not None and high >= pos.take_profit:
                    hit = (pos.take_profit, "TP")
            else:
                if pos.stop_loss is not None and high >= pos.stop_loss:
                    hit = (pos.stop_loss, "SL")
                elif pos.take_profit is not None and low <= pos.take_profit:
                    hit = (pos.take_profit, "TP")
            if hit:
                exit_price, reason = hit
                del self._positions[pos.id]
                self._realized_pnl_total += self._compute_pnl(pos, exit_price)
                triggered.append((pos, exit_price, reason))
        return triggered

    @staticmethod
    def _compute_pnl(pos: SimPosition, exit_price: float) -> float:
        direction = 1 if pos.side == "BUY" else -1
        return (exit_price - pos.entry_price) * direction * pos.units

    async def place_order(
        self,
        instrument: str,
        side: Side,
        units: int,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResult:
        if self._last_price is None:
            return OrderResult(success=False, broker_trade_id=None, fill_price=None, message="no price yet")
        trade_id = str(self._next_id)
        self._next_id += 1
        self._positions[trade_id] = SimPosition(
            id=trade_id,
            instrument=instrument,
            side=side,
            units=units,
            entry_price=self._last_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        return OrderResult(success=True, broker_trade_id=trade_id, fill_price=self._last_price, message="filled (simulated)")

    def modify_position(self, trade_id: str, stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> bool:
        pos = self._positions.get(trade_id)
        if pos is None:
            return False
        if stop_loss is not None:
            pos.stop_loss = stop_loss
        if take_profit is not None:
            pos.take_profit = take_profit
        return True

    async def close_position(self, trade_id: str) -> OrderResult:
        pos = self._positions.pop(trade_id, None)
        if pos is None:
            return OrderResult(success=False, broker_trade_id=trade_id, fill_price=None, message="not found")
        price = self._last_price if self._last_price is not None else pos.entry_price
        self._realized_pnl_total += self._compute_pnl(pos, price)
        return OrderResult(success=True, broker_trade_id=trade_id, fill_price=price, message="closed (simulated)")

    async def get_open_trades(self) -> list[BrokerTrade]:
        return [
            BrokerTrade(
                broker_trade_id=p.id,
                instrument=p.instrument,
                side=p.side,
                units=p.units,
                entry_price=p.entry_price,
                unrealized_pnl=self._compute_pnl(p, self._last_price) if self._last_price is not None else 0.0,
                stop_loss=p.stop_loss,
                take_profit=p.take_profit,
            )
            for p in self._positions.values()
        ]

    async def get_account_state(self) -> AccountState:
        unrealized = (
            sum(self._compute_pnl(p, self._last_price) for p in self._positions.values())
            if self._last_price is not None
            else 0.0
        )
        return AccountState(
            balance=self._starting_balance + self._realized_pnl_total,
            unrealized_pnl=unrealized,
            margin_available=self._starting_balance + self._realized_pnl_total,
            open_trade_count=len(self._positions),
        )

    async def get_candles(self, instrument: str, granularity: str, count: int = 500) -> list[Candle]:
        raise NotImplementedError("SimulatedBrokerAdapter is execution-only; use the data-source broker for candles.")

    async def stream_prices(self, instrument: str) -> AsyncIterator[PriceTick]:
        raise NotImplementedError("SimulatedBrokerAdapter is execution-only; use the data-source broker for streaming.")
        yield  # pragma: no cover — unreachable, keeps this an async generator for typing
