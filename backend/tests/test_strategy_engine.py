"""StrategyEngine.start() seeds its candle history from the broker before any
live evaluation happens — _fetch_fresh_history guards against a real bug found
on the live account: right after a (re)connect, MT5 can briefly hand back a
seed whose newest bar is actually stale (minutes/hours old), which silently
poisons every EMA computed off it (ema50 especially, since a span=50 EMA needs
~100+ fresh bars to fully displace a bad seed) until enough live candles wash
it out.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.broker.base import Candle
from app.settings_store import get_setting, set_setting
from app.strategies.base import EvaluationResult, Signal
from app.strategy_engine import StrategyEngine
from app.ws.manager import ConnectionManager


class _FakeStrategy:
    id = "fake"
    display_name = "Fake"

    def required_history(self) -> int:
        return 1

    def evaluate(self, candles) -> EvaluationResult:
        return EvaluationResult(thought="thinking", signal=Signal(action="NONE", reason=""))


def _candles(n: int, end_time: datetime) -> list[Candle]:
    return [
        Candle(time=end_time - timedelta(minutes=n - 1 - i), open=2400.0, high=2401.0, low=2399.0, close=2400.0)
        for i in range(n)
    ]


class _QueuedBroker:
    """Returns each queued batch in order, one per get_candles() call — lets a
    test simulate "stale, stale, then finally fresh" without a real MT5."""

    def __init__(self, batches: list[list[Candle]]):
        self._batches = batches
        self.calls = 0

    async def get_candles(self, instrument, granularity, count):
        batch = self._batches[min(self.calls, len(self._batches) - 1)]
        self.calls += 1
        return batch


def _engine(broker) -> StrategyEngine:
    return StrategyEngine(_FakeStrategy(), broker, "XAU_USD", "M1", ConnectionManager(), history_size=5)


@pytest.mark.asyncio
async def test_fresh_history_is_accepted_on_first_try():
    now = datetime.now(timezone.utc)
    broker = _QueuedBroker([_candles(5, now)])
    engine = _engine(broker)

    await engine.start()

    assert broker.calls == 1
    assert len(engine._candles) == 5


@pytest.mark.asyncio
async def test_stale_history_is_retried_until_fresh(monkeypatch):
    monkeypatch.setattr("app.strategy_engine.asyncio.sleep", _no_sleep)
    set_setting("bot_enabled", "true")
    now = datetime.now(timezone.utc)
    stale = _candles(5, now - timedelta(hours=2))  # newest bar 2h old
    fresh = _candles(5, now)
    broker = _QueuedBroker([stale, stale, fresh])
    engine = _engine(broker)

    await engine.start()

    assert broker.calls == 3
    assert engine._candles[-1].close == fresh[-1].close
    assert engine._candles[-1].time == fresh[-1].time
    assert get_setting("bot_enabled") == "true"  # recovered before exhausting retries — no need to trip the switch


@pytest.mark.asyncio
async def test_gives_up_and_disables_bot_after_max_attempts(monkeypatch):
    # Regression test: staying stale forever used to mean silently trading on
    # bad data (the exact bug that let two real SELL trades through against the
    # EMA50 trend rule on the live account) — it must now refuse to trade blind
    # instead, by tripping the kill switch rather than proceeding normally.
    monkeypatch.setattr("app.strategy_engine.asyncio.sleep", _no_sleep)
    set_setting("bot_enabled", "true")
    now = datetime.now(timezone.utc)
    stale = _candles(5, now - timedelta(hours=2))
    broker = _QueuedBroker([stale])
    engine = _engine(broker)

    await engine.start()

    assert broker.calls == 5  # default max_attempts
    assert len(engine._candles) == 5  # still seeded with whatever it last got, not left empty
    assert get_setting("bot_enabled") == "false"
    assert get_setting("auto_stop_message")  # non-empty — persisted so a page reload still explains why


async def _no_sleep(_seconds):
    return None
