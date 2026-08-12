from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class ThoughtLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    strategy_id: str
    candle_time: datetime
    text: str
    signal: str = "NONE"  # NONE | BUY | SELL | CLOSE
    indicators_json: str = "{}"


class Trade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    broker_trade_id: Optional[str] = None
    instrument: str
    side: str  # BUY | SELL
    status: str = "OPEN"  # OPEN | CLOSED
    entry_price: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: Optional[str] = None  # SL | TP | MANUAL
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    units: int
    pnl: Optional[float] = None
    strategy_id: str
    signal_reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AppSetting(SQLModel, table=True):
    key: str = Field(primary_key=True)
    value: str


class StrategyConfig(SQLModel, table=True):
    id: str = Field(primary_key=True)  # slug, e.g. "ma_crossover" or "custom-<uuid>"
    display_name: str
    kind: str  # builtin | custom
    dsl_json: Optional[str] = None  # custom strategies only
    params_json: str = "{}"  # builtin param overrides
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class JournalNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    trade_id: Optional[int] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    note_text: str
    context_json: str = "{}"
    zone_json: Optional[str] = None  # {start_time, end_time, price_low, price_high}


class ChatMessage(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    role: str  # user | assistant
    text: str
    trade_id: Optional[int] = None
    zone_json: Optional[str] = None  # {start_time, end_time, price_low, price_high}


class FeedbackRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    description: str
    conditions_json: str  # same condition grammar as the strategy DSL
    action: str = "block_entry"  # block_entry | block_side
    side_filter: Optional[str] = None  # BUY | SELL | None (= both)
    is_active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
