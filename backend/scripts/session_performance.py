"""Breaks down real closed-trade performance by forex trading session
(Tokyo / London / New York / the London-NY overlap) to see which hours
have actually been best to run the bot.

Timestamp correction: Trade.entry_time/exit_time come from the MT5 broker's
candle.time (see app/broker/mt5.py), which is labeled UTC in code but is
actually the broker server's local clock (a well-known MT5 quirk — the
terminal reports bar times "as if" the server's local time were UTC). This
was measured directly against this DB's own timestamp column (which uses
Python's real datetime.now(timezone.utc)) across 30+ consecutive rows and
came out to a rock-steady +3.00h offset (broker server ahead of true UTC —
consistent with a EEST/UTC+3 server). That +3h is subtracted below before
bucketing into UTC session windows; if the broker's server timezone changes
(e.g. winter EET/UTC+2), re-measure via scripts/measure_broker_offset.py
logic (compare a fresh trade's exit_time to real current UTC) and adjust
BROKER_UTC_OFFSET_HOURS.

Usage (from backend/, with the venv active):
    python scripts/session_performance.py
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "bott.db"
BROKER_UTC_OFFSET_HOURS = 3

# (label, start_hour_utc, end_hour_utc) — half-open [start, end)
SESSIONS = [
    ("Tokyo (Asian)", 0, 9),
    ("London", 8, 17),
    ("New York", 13, 22),
    ("London/NY overlap", 13, 17),
]


def load_closed_trades() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT entry_time, side, pnl FROM trade "
        "WHERE status = 'CLOSED' AND strategy_id = 'scalping' ORDER BY entry_time ASC"
    )
    rows = cur.fetchall()
    conn.close()

    trades = []
    for entry_time_str, side, pnl in rows:
        broker_dt = datetime.strptime(entry_time_str, "%Y-%m-%d %H:%M:%S.%f")
        true_utc = broker_dt - timedelta(hours=BROKER_UTC_OFFSET_HOURS)
        trades.append({"utc_time": true_utc, "side": side, "pnl": pnl or 0.0})
    return trades


def in_session(hour: int, start: int, end: int) -> bool:
    return start <= hour < end


def summarize(trades: list[dict]) -> None:
    print(f"{len(trades)} closed scalping trades, entry times corrected to true UTC "
          f"(broker server time - {BROKER_UTC_OFFSET_HOURS}h)\n")

    rows = []
    for label, start, end in SESSIONS:
        bucket = [t for t in trades if in_session(t["utc_time"].hour, start, end)]
        wins = sum(1 for t in bucket if t["pnl"] > 0)
        total_pnl = sum(t["pnl"] for t in bucket)
        avg_pnl = total_pnl / len(bucket) if bucket else 0.0
        win_rate = wins / len(bucket) * 100 if bucket else 0.0
        rows.append((label, f"{start:02d}:00-{end:02d}:00 UTC", len(bucket), win_rate, total_pnl, avg_pnl))

    dead_zone = [t for t in trades if t["utc_time"].hour >= 22]  # 22:00-24:00 UTC, before Tokyo opens
    if dead_zone:
        total_pnl = sum(t["pnl"] for t in dead_zone)
        wins = sum(1 for t in dead_zone if t["pnl"] > 0)
        rows.append((
            "Dead zone (post-NY, pre-Tokyo)", "22:00-24:00 UTC", len(dead_zone),
            wins / len(dead_zone) * 100, total_pnl, total_pnl / len(dead_zone),
        ))

    header = f"{'Session':<28} {'UTC window':<16} {'#':>4} {'Win%':>7} {'Total $':>10} {'Avg $/trade':>12}"
    print(header)
    print("-" * len(header))
    for label, window, count, win_rate, total_pnl, avg_pnl in rows:
        print(f"{label:<28} {window:<16} {count:>4} {win_rate:>6.1f}% {total_pnl:>+10.2f} {avg_pnl:>+12.2f}")

    scored = [r for r in rows if r[2] >= 3]  # need at least a handful of trades to say anything
    if scored:
        best = max(scored, key=lambda r: r[5])
        print(f"\nBest so far (avg $/trade, min 3 trades): {best[0]} ({best[2]} trades, {best[5]:+.2f}$/trade avg)")
    print(f"\nCaveat: only {len(trades)} trades total, spanning under two days — this is far too small a "
          f"sample to commit to a schedule. Re-run this after a week or two of real trading.")


if __name__ == "__main__":
    summarize(load_closed_trades())
