import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from app.api import (
    bot,
    candles,
    chat as chat_api,
    feedback_rules as feedback_rules_api,
    journal,
    portfolio,
    settings as settings_api,
    strategies as strategies_api,
    thoughts,
    trades,
    ws_routes,
)
from app.broker.factory import get_broker_adapter
from app.broker.simulated import SimPosition, SimulatedBrokerAdapter
from app.config import settings
from app.db import get_session, init_db
from app.market_data.service import MarketDataService
from app.models import StrategyConfig, Trade
from app.order_service import OrderService
from app.settings_store import get_setting
from app.strategies.moving_average import MovingAverageCrossoverStrategy
from app.strategies.registry import create_builtin_strategy, create_strategy_from_config
from app.strategy_engine import StrategyEngine
from app.ws.manager import ConnectionManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _load_active_strategy():
    active_id = get_setting("active_strategy_id")
    strategy = create_builtin_strategy(active_id)
    if strategy is not None:
        return strategy
    with get_session() as session:
        config = session.get(StrategyConfig, active_id)
        if config is not None:
            strategy = create_strategy_from_config(config)
    if strategy is not None:
        return strategy
    logger.warning("Configured active_strategy_id=%r not found — falling back to ma_crossover", active_id)
    return MovingAverageCrossoverStrategy()


def _load_open_positions() -> list[SimPosition]:
    """Trades still marked OPEN in the DB from before the last restart — the
    execution broker's own position book is in-memory only, so this is the
    only record of what's genuinely still open."""
    with get_session() as session:
        open_trades = session.exec(select(Trade).where(Trade.status == "OPEN")).all()
    positions = []
    for t in open_trades:
        if not t.broker_trade_id:
            logger.warning("Trade id=%s is OPEN with no broker_trade_id — skipping restore", t.id)
            continue
        positions.append(
            SimPosition(
                id=t.broker_trade_id,
                instrument=t.instrument,
                side=t.side,
                units=t.units,
                entry_price=t.entry_price,
                stop_loss=t.stop_loss,
                take_profit=t.take_profit,
            )
        )
    return positions


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.warning(
        "=== BOTT backend starting | data_source: %s | OANDA environment: %s | instrument: %s ===",
        settings.data_source.upper(),
        settings.oanda_environment.upper(),
        settings.instrument,
    )

    init_db()

    if settings.execution_mode == "live" and settings.data_source not in ("oanda", "mt5"):
        raise RuntimeError(
            f"EXECUTION_MODE=live requires DATA_SOURCE=oanda or mt5 (got {settings.data_source!r}) — "
            f"{settings.data_source} has no real order execution."
        )

    broker = get_broker_adapter(settings)
    ws_manager = ConnectionManager()

    is_live = settings.execution_mode == "live"
    if is_live:
        execution_broker = broker
        logger.warning(
            "=== EXECUTION_MODE=live — orders will be placed on the REAL broker (%s) ===",
            settings.data_source.upper(),
        )
    else:
        execution_broker = SimulatedBrokerAdapter()
        restored_positions = _load_open_positions()
        if restored_positions:
            execution_broker.seed_open_positions(restored_positions)
            logger.warning(
                "Restored %d open position(s) from DB after restart: %s",
                len(restored_positions),
                [p.id for p in restored_positions],
            )
    order_service = OrderService(
        broker=execution_broker,
        ws_manager=ws_manager,
        instrument=settings.instrument,
        granularity=settings.strategy_granularity,
        live=is_live,
    )

    strategy = _load_active_strategy()
    strategy_engine = StrategyEngine(
        strategy=strategy,
        broker=broker,
        instrument=settings.instrument,
        granularity=settings.strategy_granularity,
        ws_manager=ws_manager,
        order_service=order_service,
    )
    await strategy_engine.start()

    async def handle_candle_closed(granularity: str, candle) -> None:
        # Order matters: order_service must update the broker's current price
        # (and check existing positions' SL/TP against this candle) BEFORE the
        # strategy runs — otherwise a new signal from this candle can open a
        # trade that fills at the previous candle's stale price while its
        # SL/TP are computed off this candle's price, producing a stop/target
        # that doesn't line up with the recorded entry.
        await order_service.on_candle_closed(granularity, candle)
        await strategy_engine.on_candle_closed(granularity, candle)

    market_data_service = MarketDataService(broker, settings.instrument, ws_manager, on_candle_closed=handle_candle_closed)

    app.state.broker = broker
    app.state.execution_broker = execution_broker
    app.state.ws_manager = ws_manager
    app.state.instrument = settings.instrument
    app.state.market_data_service = market_data_service
    app.state.strategy_engine = strategy_engine
    app.state.order_service = order_service

    market_data_service.start()
    try:
        yield
    finally:
        await market_data_service.stop()


app = FastAPI(title="BOTT — Gold Trading Bot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(candles.router)
app.include_router(thoughts.router)
app.include_router(trades.router)
app.include_router(bot.router)
app.include_router(settings_api.router)
app.include_router(strategies_api.router)
app.include_router(journal.router)
app.include_router(feedback_rules_api.router)
app.include_router(portfolio.router)
app.include_router(chat_api.router)
app.include_router(ws_routes.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "instrument": settings.instrument, "environment": settings.oanda_environment}
