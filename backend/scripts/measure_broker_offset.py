"""Measures how far the MT5 broker's candle/tick timestamps drift from true
UTC — the terminal reports bar times "as if" the server's local clock were
UTC, so anything derived from candle.time (Trade.entry_time/exit_time,
ThoughtLog.candle_time) is actually offset by the broker server's real
timezone, not genuinely UTC. See scripts/session_performance.py for why this
matters (session-hour bucketing needs true UTC).

Compares the most recent ThoughtLog row's candle_time against its own
`timestamp` column (which uses Python's real datetime.now(timezone.utc), so
that one IS true UTC) — the delta is the current broker offset. Only
meaningful while candles are actively streaming (bot/market-data service
running); a stale row after a long pause will give a bogus reading.

Usage (from backend/, with the venv active, while the backend is running):
    python scripts/measure_broker_offset.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "bott.db"


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT candle_time, timestamp FROM thoughtlog ORDER BY id DESC LIMIT 5")
    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("No thoughtlog rows found.")
        return

    fmt = "%Y-%m-%d %H:%M:%S.%f"
    print(f"{'candle_time (broker)':<28} {'timestamp (true UTC)':<28} {'delta (offset)':>15}")
    for candle_time, timestamp in rows:
        ct = datetime.strptime(candle_time, fmt)
        ts = datetime.strptime(timestamp, fmt)
        delta_hours = (ts - ct).total_seconds() / 3600
        print(f"{candle_time:<28} {timestamp:<28} {delta_hours:>+14.2f}h")

    print(
        "\nIf the last few rows agree closely, that's the current broker offset — "
        "use it as BROKER_UTC_OFFSET_HOURS in session_performance.py. Skip any row "
        "right after a backend restart (candle_time may lag a stale seeded candle)."
    )


if __name__ == "__main__":
    main()
