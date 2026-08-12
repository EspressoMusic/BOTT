"""Standalone OANDA connectivity check — run this BEFORE starting the full app,
so connection/auth problems are isolated from app-wiring problems.

Usage (from backend/, with the venv active):
    python scripts/test_oanda_connection.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.broker.oanda import OandaAdapter  # noqa: E402
from app.config import settings  # noqa: E402


async def main() -> None:
    if not settings.oanda_api_token or not settings.oanda_account_id:
        print(
            "Missing OANDA_API_TOKEN / OANDA_ACCOUNT_ID.\n"
            "Copy backend/.env.example to backend/.env and fill in your practice account details."
        )
        return

    broker = OandaAdapter(
        api_token=settings.oanda_api_token,
        account_id=settings.oanda_account_id,
        environment=settings.oanda_environment,
        allow_live_trading=settings.allow_live_trading,
    )

    print(f"Fetching last 5 {settings.instrument} M1 candles...")
    candles = await broker.get_candles(settings.instrument, "M1", count=5)
    if not candles:
        print("  No candles returned — check the instrument name and account permissions.")
    for c in candles:
        print(f"  {c.time}  O={c.open} H={c.high} L={c.low} C={c.close}")

    print(f"\nStreaming live {settings.instrument} prices for ~10 seconds...")
    count = 0
    try:
        async with asyncio.timeout(10):
            async for tick in broker.stream_prices(settings.instrument):
                print(f"  tick: {tick.time}  bid={tick.bid} ask={tick.ask}")
                count += 1
    except (asyncio.TimeoutError, TimeoutError):
        pass

    if count:
        print(f"\nReceived {count} ticks. OANDA connection OK.")
    else:
        print(
            "\nNo ticks received. Gold (XAU_USD) trades ~23h/day on weekdays but is "
            "closed on weekends — if it's currently market-closed that's expected. "
            "Otherwise check your token/account id."
        )


if __name__ == "__main__":
    asyncio.run(main())
