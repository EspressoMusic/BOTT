"""OANDA v20 REST + streaming implementation of BrokerAdapter.

One config value (`environment`) drives both the REST and streaming base URLs from
a single place, so practice/live can never drift apart or get mixed up.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import AsyncIterator, Optional

import httpx

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

_REST_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}
_STREAM_HOSTS = {
    "practice": "https://stream-fxpractice.oanda.com",
    "live": "https://stream-fxtrade.oanda.com",
}


def _parse_time(value: str) -> datetime:
    # OANDA timestamps look like "2026-08-11T12:34:56.123456789Z" (nanosecond
    # precision) — Python's fromisoformat only accepts up to microseconds, so trim.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    if "." in value:
        head, _, rest = value.partition(".")
        frac, _, tz = rest.partition("+")
        value = f"{head}.{frac[:6]}+{tz}" if tz else f"{head}.{frac[:6]}"
    return datetime.fromisoformat(value)


class OandaAdapter(BrokerAdapter):
    def __init__(
        self,
        api_token: str,
        account_id: str,
        environment: str = "practice",
        allow_live_trading: bool = False,
    ):
        if environment not in _REST_HOSTS:
            raise ValueError(f"Unknown OANDA environment: {environment!r} (expected 'practice' or 'live')")
        if environment == "live" and not allow_live_trading:
            raise RuntimeError(
                "OANDA_ENVIRONMENT=live but ALLOW_LIVE_TRADING is not enabled. Refusing to start "
                "against the live account — set ALLOW_LIVE_TRADING=true only when you deliberately "
                "mean to trade real money."
            )

        self._account_id = account_id
        self._environment = environment
        self._rest_base = _REST_HOSTS[environment]
        self._stream_base = _STREAM_HOSTS[environment]
        self._headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }
        logger.warning(
            "OandaAdapter initialized | environment=%s | rest=%s",
            environment.upper(),
            self._rest_base,
        )

    async def get_candles(self, instrument: str, granularity: str, count: int = 500) -> list[Candle]:
        url = f"{self._rest_base}/v3/instruments/{instrument}/candles"
        params = {"granularity": granularity, "count": count, "price": "M"}
        async with httpx.AsyncClient(headers=self._headers, timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        candles: list[Candle] = []
        for c in data.get("candles", []):
            if not c.get("complete", False):
                continue
            mid = c["mid"]
            candles.append(
                Candle(
                    time=_parse_time(c["time"]),
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=int(c.get("volume", 0)),
                    complete=True,
                )
            )
        return candles

    async def stream_prices(self, instrument: str) -> AsyncIterator[PriceTick]:
        url = f"{self._stream_base}/v3/accounts/{self._account_id}/pricing/stream"
        params = {"instruments": instrument}
        async with httpx.AsyncClient(headers=self._headers, timeout=None) as client:
            async with client.stream("GET", url, params=params) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("type") != "PRICE":
                        continue  # filters out HEARTBEAT messages
                    bids = msg.get("bids") or []
                    asks = msg.get("asks") or []
                    if not bids or not asks:
                        continue
                    yield PriceTick(
                        instrument=msg["instrument"],
                        time=_parse_time(msg["time"]),
                        bid=float(bids[0]["price"]),
                        ask=float(asks[0]["price"]),
                    )

    async def place_order(
        self,
        instrument: str,
        side: Side,
        units: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
    ) -> OrderResult:
        signed_units = units if side == "BUY" else -units
        order: dict = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(signed_units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        if stop_loss is not None:
            order["order"]["stopLossOnFill"] = {"price": f"{stop_loss:.2f}"}
        if take_profit is not None:
            order["order"]["takeProfitOnFill"] = {"price": f"{take_profit:.2f}"}

        url = f"{self._rest_base}/v3/accounts/{self._account_id}/orders"
        async with httpx.AsyncClient(headers=self._headers, timeout=15) as client:
            resp = await client.post(url, json=order)
            data = resp.json()

        if resp.status_code >= 400:
            return OrderResult(
                success=False,
                broker_trade_id=None,
                fill_price=None,
                message=data.get("errorMessage", str(data)),
            )
        fill = data.get("orderFillTransaction")
        if fill is None:
            cancel = data.get("orderCancelTransaction", {})
            return OrderResult(
                success=False,
                broker_trade_id=None,
                fill_price=None,
                message=cancel.get("reason", "Order was not filled"),
            )
        return OrderResult(
            success=True,
            broker_trade_id=fill.get("tradeOpened", {}).get("tradeID"),
            fill_price=float(fill["price"]),
            message="filled",
        )

    async def close_position(self, trade_id: str) -> OrderResult:
        url = f"{self._rest_base}/v3/accounts/{self._account_id}/trades/{trade_id}/close"
        async with httpx.AsyncClient(headers=self._headers, timeout=15) as client:
            resp = await client.put(url)
            data = resp.json()

        if resp.status_code >= 400:
            return OrderResult(
                success=False,
                broker_trade_id=trade_id,
                fill_price=None,
                message=data.get("errorMessage", str(data)),
            )
        fill = data.get("orderFillTransaction", {})
        return OrderResult(
            success=True,
            broker_trade_id=trade_id,
            fill_price=float(fill["price"]) if "price" in fill else None,
            message="closed",
        )

    async def modify_position(
        self, trade_id: str, stop_loss: Optional[float] = None, take_profit: Optional[float] = None
    ) -> bool:
        body: dict = {}
        if stop_loss is not None:
            body["stopLoss"] = {"price": f"{stop_loss:.2f}"}
        if take_profit is not None:
            body["takeProfit"] = {"price": f"{take_profit:.2f}"}
        if not body:
            return True

        url = f"{self._rest_base}/v3/accounts/{self._account_id}/trades/{trade_id}/orders"
        async with httpx.AsyncClient(headers=self._headers, timeout=15) as client:
            resp = await client.put(url, json=body)
        return resp.status_code < 400

    async def get_open_trades(self) -> list[BrokerTrade]:
        url = f"{self._rest_base}/v3/accounts/{self._account_id}/openTrades"
        async with httpx.AsyncClient(headers=self._headers, timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        trades: list[BrokerTrade] = []
        for t in data.get("trades", []):
            units = float(t["currentUnits"])
            trades.append(
                BrokerTrade(
                    broker_trade_id=t["id"],
                    instrument=t["instrument"],
                    side="BUY" if units > 0 else "SELL",
                    units=int(abs(units)),
                    entry_price=float(t["price"]),
                    unrealized_pnl=float(t.get("unrealizedPL", 0)),
                    stop_loss=(
                        float(t["stopLossOrder"]["price"]) if "stopLossOrder" in t else None
                    ),
                    take_profit=(
                        float(t["takeProfitOrder"]["price"]) if "takeProfitOrder" in t else None
                    ),
                )
            )
        return trades

    async def get_account_state(self) -> AccountState:
        url = f"{self._rest_base}/v3/accounts/{self._account_id}/summary"
        async with httpx.AsyncClient(headers=self._headers, timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            acc = resp.json()["account"]

        return AccountState(
            balance=float(acc["balance"]),
            unrealized_pnl=float(acc["unrealizedPL"]),
            margin_available=float(acc["marginAvailable"]),
            open_trade_count=int(acc["openTradeCount"]),
        )
