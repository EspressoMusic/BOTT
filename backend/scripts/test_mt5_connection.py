"""Standalone MT5 connectivity check — run this BEFORE starting the full app,
so connection/auth problems are isolated from app-wiring problems. Read-only:
never places, modifies, or closes an order.

Usage (from backend/, with the venv active and the MT5 terminal running and
logged in — demo account recommended for this check):
    python scripts/test_mt5_connection.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.broker.mt5 import MT5Adapter  # noqa: E402
from app.config import settings  # noqa: E402


async def main() -> None:
    try:
        broker = MT5Adapter(
            symbol=settings.mt5_symbol,
            allow_live_trading=settings.allow_live_trading,
            login=settings.mt5_login or None,
            password=settings.mt5_password,
            server=settings.mt5_server,
            path=settings.mt5_terminal_path,
        )
    except RuntimeError as exc:
        print(f"Connection failed: {exc}")
        return

    account = await broker.get_account_state()
    print(f"\nAccount: balance={account.balance} margin_available={account.margin_available}")

    print(f"\nFetching last 5 {settings.mt5_symbol} M1 candles...")
    candles = await broker.get_candles(settings.mt5_symbol, "M1", count=5)
    if not candles:
        print("  No candles returned — check the symbol name and that the market is open.")
    for c in candles:
        print(f"  {c.time}  O={c.open} H={c.high} L={c.low} C={c.close}")

    print(f"\nPolling live {settings.mt5_symbol} prices for ~10 seconds...")
    count = 0
    try:
        async with asyncio.timeout(10):
            async for tick in broker.stream_prices(settings.mt5_symbol):
                print(f"  tick: {tick.time}  bid={tick.bid} ask={tick.ask}")
                count += 1
    except (asyncio.TimeoutError, TimeoutError):
        pass

    if count:
        print(f"\nReceived {count} ticks. MT5 connection OK.")
    else:
        print(
            "\nNo ticks received. Gold (XAUUSD) trades ~23h/day on weekdays but is closed on "
            "weekends — if it's currently market-closed that's expected. Otherwise check that "
            "the symbol is enabled in Market Watch."
        )


if __name__ == "__main__":
    asyncio.run(main())
