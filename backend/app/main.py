import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from app.api import (
    bot,
    candles,
    chat as chat_api,
    feedback_rules as feedback_rules_api,
    instruments as instruments_api,
    journal,
    portfolio,
    settings as settings_api,
    strategies as strategies_api,
    thoughts,
    trades,
    ws_routes,
)
from app.broker.factory import get_broker_adapter
from app.broker.mt5 import MT5Adapter
from app.broker.simulated import SimPosition, SimulatedBrokerAdapter
from app.config import settings
from app.db import get_session, init_db
from app.instruments import find_instrument, instrument_label
from app.market_data.service import MarketDataService
from app.models import StrategyConfig, Trade
from app.order_service import OrderService
from app.settings_store import get_setting, set_setting
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
    init_db()

    # The user's last-chosen instrument (via the asset picker) overrides the
    # .env default on every restart but the very first one — see
    # app.state.switch_instrument below, which persists this on every switch.
    # Must run after init_db(): on a brand new database the appsetting table
    # doesn't exist yet, and get_setting() would fail trying to query it.
    initial_instrument = get_setting("active_instrument", settings.instrument)

    logger.warning(
        "=== BOTT backend starting | data_source: %s | OANDA environment: %s | instrument: %s ===",
        settings.data_source.upper(),
        settings.oanda_environment.upper(),
        initial_instrument,
    )

    if settings.execution_mode == "live" and settings.data_source not in ("oanda", "mt5"):
        raise RuntimeError(
            f"EXECUTION_MODE=live requires DATA_SOURCE=oanda or mt5 (got {settings.data_source!r}) — "
            f"{settings.data_source} has no real order execution."
        )

    broker = get_broker_adapter(settings)
    if isinstance(broker, MT5Adapter):
        # get_broker_adapter always connects MT5Adapter to the .env default
        # symbol (settings.mt5_symbol) — if the user last switched to a
        # different instrument before this restart, align it to that
        # persisted choice now, before anything seeds candle history from it.
        # Skipping this left the broker silently trading/streaming the .env
        # default symbol under the *persisted* instrument's label — e.g. a
        # restart while BTC_USD was active reconnected to XAUUSD instead,
        # which then read as "stale" (gold's market was closed) even though
        # BTC's own data was live the whole time.
        info = find_instrument(initial_instrument)
        if info is not None:
            await broker.set_symbol(info.mt5_symbol)
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

    # OANDA honors an arbitrary `instrument` argument per-call (see
    # broker/factory.py); MT5Adapter is pinned to one symbol per instance but
    # exposes set_symbol() to switch it at runtime (see below). Yahoo and
    # Twelve Data are hardcoded gold-only with no way to switch at all.
    supports_instrument_switch = settings.data_source in ("oanda", "mt5")

    async def handle_candle_closed(granularity: str, candle) -> None:
        # Order matters: order_service must update the broker's current price
        # (and check existing positions' SL/TP against this candle) BEFORE the
        # strategy runs — otherwise a new signal from this candle can open a
        # trade that fills at the previous candle's stale price while its
        # SL/TP are computed off this candle's price, producing a stop/target
        # that doesn't line up with the recorded entry.
        #
        # Reads app.state (rather than closing over order_service/strategy_engine
        # directly) so this same callback keeps working after an instrument
        # switch swaps both of those out for fresh instances — see
        # app.state.switch_instrument below.
        await app.state.order_service.on_candle_closed(granularity, candle)
        await app.state.strategy_engine.on_candle_closed(granularity, candle)

    async def build_services(instrument: str) -> tuple[OrderService, StrategyEngine]:
        order_service = OrderService(
            broker=execution_broker,
            ws_manager=ws_manager,
            instrument=instrument,
            granularity=settings.strategy_granularity,
            live=is_live,
        )
        strategy_engine = StrategyEngine(
            strategy=_load_active_strategy(),
            broker=broker,
            instrument=instrument,
            granularity=settings.strategy_granularity,
            ws_manager=ws_manager,
            order_service=order_service,
        )
        await strategy_engine.start()
        return order_service, strategy_engine

    order_service, strategy_engine = await build_services(initial_instrument)
    market_data_service = MarketDataService(broker, initial_instrument, ws_manager, on_candle_closed=handle_candle_closed)

    app.state.broker = broker
    app.state.execution_broker = execution_broker
    app.state.ws_manager = ws_manager
    app.state.instrument = initial_instrument
    app.state.market_data_service = market_data_service
    app.state.strategy_engine = strategy_engine
    app.state.order_service = order_service
    app.state.supports_instrument_switch = supports_instrument_switch

    async def switch_instrument(new_instrument: str) -> None:
        # Caller (app/api/instruments.py) already checked supports_instrument_switch,
        # validated new_instrument, and confirmed there's no open position.
        await app.state.market_data_service.stop()
        if isinstance(broker, MT5Adapter):
            # MT5Adapter ignores the `instrument` argument passed around below —
            # it always streams/trades whatever symbol it was last told to via
            # set_symbol(), so that has to happen before build_services() seeds
            # the new StrategyEngine's candle history from this broker.
            info = find_instrument(new_instrument)
            assert info is not None  # already validated by the caller
            await broker.set_symbol(info.mt5_symbol)
        new_order_service, new_strategy_engine = await build_services(new_instrument)
        new_market_data_service = MarketDataService(
            broker, new_instrument, ws_manager, on_candle_closed=handle_candle_closed
        )

        set_setting("active_instrument", new_instrument)
        app.state.instrument = new_instrument
        app.state.order_service = new_order_service
        app.state.strategy_engine = new_strategy_engine
        app.state.market_data_service = new_market_data_service

        new_market_data_service.start()
        await ws_manager.broadcast(
            {
                "type": "instrument_changed",
                "payload": {"instrument": new_instrument, "label": instrument_label(new_instrument)},
            }
        )

    app.state.switch_instrument = switch_instrument

    market_data_service.start()
    try:
        yield
    finally:
        await app.state.market_data_service.stop()


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
app.include_router(instruments_api.router)
app.include_router(journal.router)
app.include_router(feedback_rules_api.router)
app.include_router(portfolio.router)
app.include_router(chat_api.router)
app.include_router(ws_routes.router)


@app.get("/api/health")
async def health(request: Request) -> dict:
    return {"status": "ok", "instrument": request.app.state.instrument, "environment": settings.oanda_environment}
