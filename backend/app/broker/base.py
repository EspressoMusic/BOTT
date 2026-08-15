"""Broker abstraction. Everything above this layer (strategy engine, risk manager,
order service, API routes) talks only to `BrokerAdapter` and never imports anything
broker-specific — this is what lets a future MT5Adapter (or other instruments) slot
in later without touching engine/UI code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Literal, Optional

Side = Literal["BUY", "SELL"]


@dataclass
class PriceTick:
    instrument: str
    time: datetime
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    complete: bool = True


@dataclass
class OrderResult:
    success: bool
    broker_trade_id: Optional[str]
    fill_price: Optional[float]
    message: str


@dataclass
class BrokerTrade:
    broker_trade_id: str
    instrument: str
    side: Side
    units: float
    entry_price: float
    unrealized_pnl: float
    stop_loss: Optional[float]
    take_profit: Optional[float]


@dataclass
class AccountState:
    balance: float
    unrealized_pnl: float
    margin_available: float
    open_trade_count: int


class BrokerAdapter(ABC):
    @abstractmethod
    async def stream_prices(self, instrument: str) -> AsyncIterator[PriceTick]:
        """Yield live price ticks. Must filter out heartbeats / non-price messages."""

    @abstractmethod
    async def get_candles(self, instrument: str, granularity: str, count: int = 500) -> list[Candle]:
        """Historical OHLC candles for chart backfill."""

    @abstractmethod
    async def place_order(
        self,
        instrument: str,
        side: Side,
        units: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResult:
        """Market order with optional attached stop-loss / take-profit."""

    @abstractmethod
    async def close_position(self, trade_id: str) -> OrderResult:
        """Close an open trade by broker trade id."""

    @abstractmethod
    async def get_open_trades(self) -> list[BrokerTrade]:
        """Current open trades, per the broker — source of truth for reconciliation."""

    @abstractmethod
    async def get_account_state(self) -> AccountState:
        """Balance / margin / PnL snapshot."""
