"""Picks which BrokerAdapter implementation is active, based on settings.data_source.
This is the seam a future MT5Adapter (or any other broker) plugs into — nothing
above this factory (market data service, API routes, strategy engine, frontend)
needs to know or care which concrete adapter is running.
"""

from app.broker.base import BrokerAdapter
from app.broker.mt5 import MT5Adapter
from app.broker.oanda import OandaAdapter
from app.broker.twelvedata import TwelveDataAdapter
from app.broker.yahoo import YahooFinanceAdapter
from app.config import Settings


def get_broker_adapter(settings: Settings) -> BrokerAdapter:
    if settings.data_source == "yahoo":
        return YahooFinanceAdapter()
    if settings.data_source == "twelvedata":
        return TwelveDataAdapter(api_key=settings.twelvedata_api_key)
    if settings.data_source == "oanda":
        return OandaAdapter(
            api_token=settings.oanda_api_token,
            account_id=settings.oanda_account_id,
            environment=settings.oanda_environment,
            allow_live_trading=settings.allow_live_trading,
        )
    if settings.data_source == "mt5":
        return MT5Adapter(
            symbol=settings.mt5_symbol,
            allow_live_trading=settings.allow_live_trading,
            login=settings.mt5_login or None,
            password=settings.mt5_password,
            server=settings.mt5_server,
            path=settings.mt5_terminal_path,
        )
    raise ValueError(f"Unknown DATA_SOURCE: {settings.data_source!r} (expected 'oanda', 'yahoo', 'twelvedata', or 'mt5')")
