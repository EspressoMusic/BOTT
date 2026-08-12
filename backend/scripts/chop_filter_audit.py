"""Retrospective audit of the scalping strategy's chop filter (see
app/strategies/scalping.py) — answers "is it skipping good trades or bad
ones?" by replaying the full scalping thought-log history and comparing
what the OLD strategy (every crossover = a trade) vs the NEW strategy
(crossover suppressed when the EMAs have crossed too many times recently)
would have done.

Data source: ThoughtLog stores a row for every closed M1 candle regardless
of whether it produced a signal, so `indicators.price` across all rows for
strategy_id='scalping' is a full per-minute close-price series — enough to
recompute the EMAs and simulate forward without needing separately stored
OHLC candle history (which isn't persisted long-term).

Caveat: outcomes are simulated using 1-minute CLOSE prices only (no intrabar
high/low), since that's all that's retained. A trade could touch its real
stop/target intrabar before a close crosses it, so treat this as a directional
read, not exact P&L.

Usage (from backend/, with the venv active):
    python scripts/chop_filter_audit.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app.strategies.scalping import ScalpingStrategy  # noqa: E402

DB_PATH = Path(__file__).resolve().parent.parent / "bott.db"
MAX_HORIZON_MINUTES = 180  # give a simulated trade up to 3h to resolve before calling it a timeout


def load_price_series() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT candle_time, indicators_json FROM thoughtlog "
        "WHERE strategy_id = 'scalping' ORDER BY candle_time ASC"
    )
    rows = cur.fetchall()
    conn.close()
    times, prices = [], []
    for candle_time, indicators_json in rows:
        d = json.loads(indicators_json)
        if "price" not in d:
            continue
        times.append(candle_time)
        prices.append(d["price"])
    return pd.DataFrame({"candle_time": times, "close": prices})


def simulate_outcome(closes: pd.Series, entry_idx: int, side: str, strategy: ScalpingStrategy) -> tuple[str, int]:
    """Walk forward from entry_idx using close prices only. Returns (outcome, minutes)."""
    entry_price = closes.iloc[entry_idx]
    direction = 1 if side == "BUY" else -1
    stop_loss = entry_price - direction * strategy.stop_distance
    take_profit = entry_price + direction * strategy.target_distance

    end = min(entry_idx + MAX_HORIZON_MINUTES, len(closes) - 1)
    for i in range(entry_idx + 1, end + 1):
        price = closes.iloc[i]
        hit_tp = (price >= take_profit) if direction == 1 else (price <= take_profit)
        hit_sl = (price <= stop_loss) if direction == 1 else (price >= stop_loss)
        if hit_tp:
            return "WIN", i - entry_idx
        if hit_sl:
            return "LOSS", i - entry_idx
    return "TIMEOUT", end - entry_idx


def main() -> None:
    strategy = ScalpingStrategy()
    df = load_price_series()
    print(f"Loaded {len(df)} minutes of scalping price history "
          f"({df['candle_time'].iloc[0]} -> {df['candle_time'].iloc[-1]}, broker server time)\n")

    ema_fast = df["close"].ewm(span=strategy.fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=strategy.slow, adjust=False).mean()
    above = (ema_fast - ema_slow) > 0
    closes = df["close"]

    suppressed, still_allowed = [], []

    for i in range(strategy.slow + strategy.chop_lookback + 1, len(df) - 1):
        crossed_up = not above.iloc[i - 1] and above.iloc[i]
        crossed_down = above.iloc[i - 1] and not above.iloc[i]
        if not (crossed_up or crossed_down):
            continue

        window = above.iloc[i - strategy.chop_lookback : i + 1]
        cross_count = int((window != window.shift(1)).iloc[1:].sum())
        choppy = cross_count > strategy.chop_max_crosses
        side = "BUY" if crossed_up else "SELL"

        outcome, minutes = simulate_outcome(closes, i, side, strategy)
        record = {
            "candle_time": df["candle_time"].iloc[i],
            "side": side,
            "cross_count": cross_count,
            "outcome": outcome,
            "minutes": minutes,
        }
        (suppressed if choppy else still_allowed).append(record)

    units = 10  # matches risk_units default / observed trade.units in the DB
    win_amount = strategy.target_distance * units
    loss_amount = strategy.stop_distance * units

    def summarize(label: str, records: list[dict]) -> None:
        wins = sum(1 for r in records if r["outcome"] == "WIN")
        losses = sum(1 for r in records if r["outcome"] == "LOSS")
        timeouts = sum(1 for r in records if r["outcome"] == "TIMEOUT")
        resolved = wins + losses
        pnl = wins * win_amount - losses * loss_amount
        print(f"--- {label} ({len(records)} signals) ---")
        print(f"  WIN: {wins}   LOSS: {losses}   TIMEOUT(>{MAX_HORIZON_MINUTES}m): {timeouts}")
        if resolved:
            print(f"  win rate (resolved only): {wins / resolved * 100:.1f}%")
        print(f"  simulated $ if taken (resolved signals, ${win_amount:.0f}/${-loss_amount:.0f}): {pnl:+.2f}$\n")

    print("=" * 70)
    print("Signals the NEW filter SUPPRESSES (would have fired under the old, unfiltered rule):")
    summarize("suppressed by chop filter", suppressed)

    print("Signals the NEW filter STILL ALLOWS (baseline, for comparison):")
    summarize("allowed (not choppy)", still_allowed)

    print("=" * 70)
    if suppressed:
        s_wins = sum(1 for r in suppressed if r["outcome"] == "WIN")
        s_losses = sum(1 for r in suppressed if r["outcome"] == "LOSS")
        net = s_wins * win_amount - s_losses * loss_amount
        verdict = "the filter is net HELPFUL so far" if net < 0 else "the filter may be cutting off net-positive trades so far"
        print(f"Net effect of suppressing those {len(suppressed)} signals: {-net:+.2f}$ saved/lost -> {verdict}")
        print("(sample size is small — re-run this after a few more days of data before trusting it fully.)")


if __name__ == "__main__":
    main()
