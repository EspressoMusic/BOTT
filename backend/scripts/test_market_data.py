"""Standalone connectivity check for whichever DATA_SOURCE is configured
(oanda or yahoo) — run this BEFORE starting the full app, so connection
problems are isolated from app-wiring problems.

Usage (from backend/, with the venv active):
    python scripts/test_market_data.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.broker.factory import get_broker_adapter  # noqa: E402
from app.config import settings  # noqa: E402


async def main() -> None:
    print(f"DATA_SOURCE = {settings.data_source}")
    broker = get_broker_adapter(settings)

    print(f"\nFetching last 5 {settings.instrument} M1 candles...")
    candles = await broker.get_candles(settings.instrument, "M1", count=5)
    if not candles:
        print("  No candles returned — check settings/credentials.")
    for c in candles:
        print(f"  {c.time}  O={c.open} H={c.high} L={c.low} C={c.close}")

    print(f"\nStreaming live {settings.instrument} prices for ~15 seconds...")
    count = 0
    try:
        async with asyncio.timeout(15):
            async for tick in broker.stream_prices(settings.instrument):
                print(f"  tick: {tick.time}  bid={tick.bid} ask={tick.ask}")
                count += 1
    except (asyncio.TimeoutError, TimeoutError):
        pass

    if count:
        print(f"\nReceived {count} tick(s). Connection OK.")
    else:
        print(
            "\nNo ticks received. If using OANDA: gold trades ~23h/day on weekdays but "
            "is closed on weekends — that's expected then. Otherwise check credentials/settings."
        )


if __name__ == "__main__":
    asyncio.run(main())
