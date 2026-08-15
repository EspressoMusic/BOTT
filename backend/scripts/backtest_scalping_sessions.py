"""Backtest ScalpingStrategy over the last HISTORY_DAYS of real M1 history
from MT5, restricted to the London/New York trading window
(SESSION_START_HOUR-SESSION_END_HOUR, UTC) — new trades only open with a
candle time inside that window; a trade already open is still managed to its
stop/target even if that crosses the boundary (no forced end-of-window close).

Uses the strategy's actual evaluate() (same code path the live bot runs) and
real OHLC, so SL/TP hits are checked against intrabar [low, high] the same
way OrderService/SimulatedBrokerAdapter do — not close-only approximations.
Also simulates the breakeven-extension order_service now applies (moves the
stop to breakeven and extends the target once price reaches the original
take-profit) since that's part of what actually happens to a live trade
today.

Timestamp correction: MT5 candle time is labeled UTC in code but is actually
the broker server's local clock (see scripts/session_performance.py) — a
measured +3h offset. Subtracted here before session filtering so "08:00" and
"20:00" mean true UTC, matching the London/New York session convention used
elsewhere in this codebase.

Usage (from backend/, with the venv active):
    python scripts/backtest_scalping_sessions.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import MetaTrader5 as mt5  # noqa: E402
import pandas as pd  # noqa: E402

from app.strategies.scalping import ScalpingStrategy  # noqa: E402

SYMBOL = "XAUUSD"
HISTORY_DAYS = 30
SESSION_START_HOUR = 8  # UTC — London open
SESSION_END_HOUR = 20  # UTC
BROKER_UTC_OFFSET_HOURS = 3  # see scripts/session_performance.py
UNITS = 10  # matches the app's risk_units default
BREAKEVEN_EXTEND_RR = 4.0  # matches OrderService's default


def load_candles() -> pd.DataFrame:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}. Is the terminal running and logged in?")
    if not mt5.symbol_select(SYMBOL, True):
        mt5.shutdown()
        raise RuntimeError(f"MT5 symbol {SYMBOL!r} not found in Market Watch.")

    date_to = datetime.now(timezone.utc)
    date_from = date_to - timedelta(days=HISTORY_DAYS)
    rates = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M1, date_from, date_to)
    mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise RuntimeError("MT5 returned no candles for the requested range.")

    df = pd.DataFrame(rates)
    df["time_utc"] = pd.to_datetime(df["time"], unit="s", utc=True) - pd.Timedelta(hours=BROKER_UTC_OFFSET_HOURS)
    return df[["time_utc", "open", "high", "low", "close"]].reset_index(drop=True)


def in_session(ts: pd.Timestamp) -> bool:
    return SESSION_START_HOUR <= ts.hour < SESSION_END_HOUR


def run_backtest(df: pd.DataFrame, strategy: ScalpingStrategy) -> list[dict]:
    trades: list[dict] = []
    open_trade: dict | None = None

    for i in range(strategy.required_history(), len(df)):
        window = df.iloc[: i + 1]
        candle_time = df["time_utc"].iloc[i]
        high, low, close = df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]

        if open_trade is not None:
            side = open_trade["side"]
            direction = 1 if side == "BUY" else -1

            # Original-target reached and not yet extended -> breakeven + push target out.
            # Conservative tie-break matching SimulatedBrokerAdapter: if this same wide
            # candle would have also hit the ORIGINAL stop, treat that as having happened
            # first (don't extend into a stop that already would have triggered).
            already_extended = (open_trade["stop_loss"] - open_trade["entry_price"]) * direction >= -1e-9
            reached_original_tp = high >= open_trade["take_profit"] if side == "BUY" else low <= open_trade["take_profit"]
            hit_original_sl = low <= open_trade["stop_loss"] if side == "BUY" else high >= open_trade["stop_loss"]
            if not already_extended and reached_original_tp and not hit_original_sl:
                risk = abs(open_trade["entry_price"] - open_trade["stop_loss"])
                open_trade["stop_loss"] = open_trade["entry_price"]
                open_trade["take_profit"] = open_trade["entry_price"] + direction * BREAKEVEN_EXTEND_RR * risk
                open_trade["extended"] = True

            hit_sl = low <= open_trade["stop_loss"] if side == "BUY" else high >= open_trade["stop_loss"]
            hit_tp = high >= open_trade["take_profit"] if side == "BUY" else low <= open_trade["take_profit"]
            if hit_sl or hit_tp:
                exit_price = open_trade["stop_loss"] if hit_sl else open_trade["take_profit"]
                pnl = (exit_price - open_trade["entry_price"]) * direction * UNITS
                trades.append(
                    {
                        "entry_time": open_trade["entry_time"],
                        "exit_time": candle_time,
                        "side": side,
                        "reason": "SL" if hit_sl else "TP",
                        "pnl": pnl,
                        "extended": open_trade["extended"],
                    }
                )
                open_trade = None
            continue

        if not in_session(candle_time):
            continue

        result = strategy.evaluate(window)
        if result.signal.action not in ("BUY", "SELL"):
            continue

        direction = 1 if result.signal.action == "BUY" else -1
        stop_loss = result.signal.stop_loss if result.signal.stop_loss is not None else close - direction * strategy.stop_distance
        take_profit = (
            result.signal.take_profit if result.signal.take_profit is not None else close + direction * strategy.target_distance
        )
        open_trade = {
            "side": result.signal.action,
            "entry_price": close,
            "entry_time": candle_time,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "extended": False,
        }

    return trades


def summarize(trades: list[dict]) -> None:
    if not trades:
        print("No trades were simulated in this window.")
        return

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total_pnl = sum(t["pnl"] for t in trades)
    win_rate = len(wins) / len(trades) * 100

    cumulative, peak, max_dd = 0.0, 0.0, 0.0
    for t in trades:
        cumulative += t["pnl"]
        peak = max(peak, cumulative)
        max_dd = max(max_dd, peak - cumulative)

    extended = [t for t in trades if t.get("extended")]
    extended_won = [t for t in extended if t["pnl"] > 0]
    extended_breakeven = [t for t in extended if t["pnl"] <= 0]
    plain_sl = [t for t in trades if not t.get("extended") and t["reason"] == "SL"]

    print(f"Trades: {len(trades)}  (BUY: {sum(1 for t in trades if t['side']=='BUY')}, "
          f"SELL: {sum(1 for t in trades if t['side']=='SELL')})")
    print(f"Win rate: {win_rate:.1f}%  ({len(wins)} wins / {len(losses)} losses)")
    print(f"Total PnL: {total_pnl:+.2f}$")
    print(f"Avg win: {(sum(t['pnl'] for t in wins) / len(wins)) if wins else 0:+.2f}$   "
          f"Avg loss: {(sum(t['pnl'] for t in losses) / len(losses)) if losses else 0:+.2f}$")
    print(f"Max drawdown (equity curve): {max_dd:.2f}$")
    print(f"\nBreakeven-extension breakdown:")
    print(f"  Reached original TP and got extended: {len(extended)} "
          f"(of those: {len(extended_won)} ran to the extended target, {len(extended_breakeven)} reversed back to breakeven)")
    if extended:
        print(f"    -> combined PnL from extended trades: {sum(t['pnl'] for t in extended):+.2f}$")
    print(f"  Closed at the original stop-loss (never reached TP): {len(plain_sl)} "
          f"({sum(t['pnl'] for t in plain_sl):+.2f}$)")


def main() -> None:
    strategy = ScalpingStrategy()
    df = load_candles()
    print(
        f"Loaded {len(df)} M1 candles, {df['time_utc'].iloc[0]} -> {df['time_utc'].iloc[-1]} (true UTC)\n"
        f"Session filter for NEW entries: {SESSION_START_HOUR:02d}:00-{SESSION_END_HOUR:02d}:00 UTC "
        "(London + New York)\n"
    )
    trades = run_backtest(df, strategy)
    summarize(trades)


if __name__ == "__main__":
    main()
