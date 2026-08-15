"""MetaTrader 5 implementation of BrokerAdapter.

Unlike OANDA (a remote REST/streaming API), MT5's Python package talks to a
MetaTrader 5 *terminal application* running locally on this machine over local
IPC — there is no network client to configure. `mt5.initialize()` simply
attaches to whichever account is already logged into the running terminal
(unless login/password/server are explicitly given, in which case it drives
the terminal to log into that account itself).

The underlying `MetaTrader5` module is synchronous and keeps one connection
per process; every call here is routed through a single dedicated worker
thread (`_call`) so concurrent async callers never hit the C API from
multiple OS threads at once.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import MetaTrader5 as mt5

from app.broker.base import (
    AccountState,
    BrokerAdapter,
    BrokerTrade,
    Candle,
    OrderResult,
    PriceTick,
    Side,
)

logger = logging.getLogger(__name__)

_MAGIC = 20260812  # arbitrary — tags orders/positions this bot opened, for filtering

_TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1": mt5.TIMEFRAME_H1,
}


class MT5Adapter(BrokerAdapter):
    def __init__(
        self,
        symbol: str,
        allow_live_trading: bool = False,
        login: Optional[int] = None,
        password: str = "",
        server: str = "",
        path: str = "",
        poll_interval: float = 0.5,
    ):
        self._symbol = symbol
        self._poll_interval = poll_interval
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mt5")

        init_kwargs: dict = {}
        if path:
            init_kwargs["path"] = path
        if login:
            init_kwargs.update(login=login, password=password, server=server)

        if not mt5.initialize(**init_kwargs):
            raise RuntimeError(
                f"MT5 initialize() failed: {mt5.last_error()}. Make sure the MetaTrader 5 "
                "terminal is installed, running, and logged into an account."
            )

        if not mt5.symbol_select(symbol, True):
            mt5.shutdown()
            raise RuntimeError(f"MT5 symbol {symbol!r} was not found / could not be added to Market Watch.")

        account = mt5.account_info()
        if account is None:
            mt5.shutdown()
            raise RuntimeError(f"MT5 account_info() failed: {mt5.last_error()}")

        is_live = account.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL
        if is_live and not allow_live_trading:
            mt5.shutdown()
            raise RuntimeError(
                f"The MT5 terminal is logged into a LIVE account (login={account.login}, "
                f"server={account.server!r}) but ALLOW_LIVE_TRADING is not enabled. Refusing to "
                "start against a real-money account - log into a demo account in the terminal, "
                "or set ALLOW_LIVE_TRADING=true only when you deliberately mean to trade real money."
            )

        info = mt5.symbol_info(symbol)
        self._contract_size = info.trade_contract_size
        self._volume_min = info.volume_min
        self._volume_step = info.volume_step

        logger.warning(
            "MT5Adapter initialized | account=%s | server=%s | mode=%s | symbol=%s | contract_size=%s",
            account.login,
            account.server,
            "LIVE" if is_live else "DEMO",
            symbol,
            self._contract_size,
        )

    async def set_symbol(self, symbol: str) -> None:
        """Switch which MT5 symbol this adapter streams/trades/reports on — used
        when the frontend's asset picker switches instrument. Re-selects the new
        symbol in Market Watch and refreshes its contract/volume metadata, the
        same validation __init__ does for the initial symbol."""

        def _do() -> None:
            if not mt5.symbol_select(symbol, True):
                raise RuntimeError(f"MT5 symbol {symbol!r} was not found / could not be added to Market Watch.")
            info = mt5.symbol_info(symbol)
            if info is None:
                raise RuntimeError(f"MT5 symbol_info({symbol!r}) failed: {mt5.last_error()}")
            self._symbol = symbol
            self._contract_size = info.trade_contract_size
            self._volume_min = info.volume_min
            self._volume_step = info.volume_step

        await self._call(_do)
        logger.warning("MT5Adapter switched active symbol to %s", symbol)

    async def _call(self, fn, *args, **kwargs):
        # MetaTrader5's C extension breaks on some functions (order_send/order_check
        # among them) when called via a site that unpacks *args and **kwargs together
        # — even with kwargs empty — raising last_error() (-2, 'Unnamed arguments not
        # allowed'). Dispatching through two single-unpack lambdas avoids that call
        # shape entirely; every call site here uses purely positional or purely
        # keyword arguments, never both, so this covers all real usage.
        loop = asyncio.get_running_loop()
        if kwargs:
            return await loop.run_in_executor(self._executor, lambda: fn(**kwargs))
        return await loop.run_in_executor(self._executor, lambda: fn(*args))

    def _units_to_volume(self, units: float) -> float:
        raw_lots = units / self._contract_size
        steps = max(round(raw_lots / self._volume_step), 1)
        return round(steps * self._volume_step, 8)

    def _filling_type(self, info) -> int:
        # info.filling_mode is a bitmask of the SYMBOL_FILLING_* flags from MQL5's
        # ENUM_SYMBOL_TRADE_EXECUTION — the Python package exposes ORDER_FILLING_*
        # (what to send back on an order) but not these SYMBOL_FILLING_* bit values
        # (what the symbol supports), so the bits are checked by their raw values
        # here: FOK=1, IOC=2.
        mode = info.filling_mode
        if mode & 2:  # SYMBOL_FILLING_IOC
            return mt5.ORDER_FILLING_IOC
        if mode & 1:  # SYMBOL_FILLING_FOK
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    async def get_candles(self, instrument: str, granularity: str, count: int = 500) -> list[Candle]:
        timeframe = _TIMEFRAMES.get(granularity)
        if timeframe is None:
            raise ValueError(f"Unsupported granularity for MT5: {granularity!r} (expected one of {list(_TIMEFRAMES)})")

        # pos=1 skips the current, still-forming bar (pos=0) — every returned
        # candle is a closed one, matching how the OANDA adapter filters.
        rates = await self._call(mt5.copy_rates_from_pos, self._symbol, timeframe, 1, count)
        if rates is None:
            return []
        return [
            Candle(
                time=datetime.fromtimestamp(int(row["time"]), tz=timezone.utc),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["tick_volume"]),
                complete=True,
            )
            for row in rates
        ]

    async def stream_prices(self, instrument: str) -> AsyncIterator[PriceTick]:
        # MT5's Python API has no push/streaming feed — poll the latest tick instead.
        last_time_msc: Optional[int] = None
        while True:
            tick = await self._call(mt5.symbol_info_tick, self._symbol)
            if tick is not None and tick.time_msc != last_time_msc:
                last_time_msc = tick.time_msc
                yield PriceTick(
                    instrument=self._symbol,
                    time=datetime.fromtimestamp(tick.time_msc / 1000, tz=timezone.utc),
                    bid=tick.bid,
                    ask=tick.ask,
                )
            await asyncio.sleep(self._poll_interval)

    async def place_order(
        self,
        instrument: str,
        side: Side,
        units: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResult:
        tick = await self._call(mt5.symbol_info_tick, self._symbol)
        info = await self._call(mt5.symbol_info, self._symbol)
        if tick is None or info is None:
            return OrderResult(success=False, broker_trade_id=None, fill_price=None, message="no price available")

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self._symbol,
            "volume": self._units_to_volume(units),
            "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": tick.ask if side == "BUY" else tick.bid,
            "deviation": 20,
            "magic": _MAGIC,
            "comment": "BOTT",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_type(info),
        }
        if stop_loss is not None:
            request["sl"] = round(stop_loss, info.digits)
        if take_profit is not None:
            request["tp"] = round(take_profit, info.digits)

        result = await self._call(mt5.order_send, request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result is not None else mt5.last_error()
            comment = result.comment if result is not None else ""
            return OrderResult(
                success=False, broker_trade_id=None, fill_price=None, message=f"order_send failed: retcode={code} {comment}"
            )

        return OrderResult(success=True, broker_trade_id=str(result.order), fill_price=result.price, message="filled")

    async def close_position(self, trade_id: str) -> OrderResult:
        ticket = int(trade_id)
        positions = await self._call(mt5.positions_get, ticket=ticket)
        if not positions:
            return OrderResult(success=False, broker_trade_id=trade_id, fill_price=None, message="position not found")
        pos = positions[0]

        tick = await self._call(mt5.symbol_info_tick, pos.symbol)
        info = await self._call(mt5.symbol_info, pos.symbol)
        if tick is None or info is None:
            return OrderResult(success=False, broker_trade_id=trade_id, fill_price=None, message="no price available")

        closing_is_buy = pos.type == mt5.POSITION_TYPE_SELL  # close with the opposite side of the open position
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": mt5.ORDER_TYPE_BUY if closing_is_buy else mt5.ORDER_TYPE_SELL,
            "position": ticket,
            "price": tick.ask if closing_is_buy else tick.bid,
            "deviation": 20,
            "magic": _MAGIC,
            "comment": "BOTT close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_type(info),
        }
        result = await self._call(mt5.order_send, request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            code = result.retcode if result is not None else mt5.last_error()
            comment = result.comment if result is not None else ""
            return OrderResult(
                success=False, broker_trade_id=trade_id, fill_price=None, message=f"close failed: retcode={code} {comment}"
            )

        return OrderResult(success=True, broker_trade_id=trade_id, fill_price=result.price, message="closed")

    async def modify_position(
        self, trade_id: str, stop_loss: Optional[float] = None, take_profit: Optional[float] = None
    ) -> bool:
        ticket = int(trade_id)
        positions = await self._call(mt5.positions_get, ticket=ticket)
        if not positions:
            return False
        pos = positions[0]
        info = await self._call(mt5.symbol_info, pos.symbol)

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": ticket,
            "sl": round(stop_loss, info.digits) if stop_loss is not None else pos.sl,
            "tp": round(take_profit, info.digits) if take_profit is not None else pos.tp,
        }
        result = await self._call(mt5.order_send, request)
        return result is not None and result.retcode == mt5.TRADE_RETCODE_DONE

    async def get_open_trades(self) -> list[BrokerTrade]:
        positions = await self._call(mt5.positions_get, symbol=self._symbol)
        if not positions:
            return []
        return [
            BrokerTrade(
                broker_trade_id=str(p.ticket),
                instrument=p.symbol,
                side="BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                units=round(p.volume * self._contract_size, 8),
                entry_price=p.price_open,
                unrealized_pnl=p.profit,
                stop_loss=p.sl if p.sl else None,
                take_profit=p.tp if p.tp else None,
            )
            for p in positions
        ]

    async def get_account_state(self) -> AccountState:
        account = await self._call(mt5.account_info)
        positions = await self._call(mt5.positions_get, symbol=self._symbol)
        return AccountState(
            balance=account.balance,
            unrealized_pnl=account.profit,
            margin_available=account.margin_free,
            open_trade_count=len(positions) if positions else 0,
        )
