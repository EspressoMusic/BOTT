from datetime import datetime, timedelta, timezone

from app.broker.base import PriceTick
from app.market_data.aggregator import CandleAggregator

_BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _tick(second_offset: int, price: float) -> PriceTick:
    return PriceTick(
        instrument="XAU_USD",
        time=_BASE + timedelta(seconds=second_offset),
        bid=price - 0.1,
        ask=price + 0.1,
    )


def test_single_tick_opens_candle():
    agg = CandleAggregator(["M1"])
    events = agg.apply_tick(_tick(0, 2400.0))

    assert len(events) == 1
    assert events[0].granularity == "M1"
    assert events[0].closed is False
    assert events[0].candle.open == events[0].candle.close == 2400.0


def test_ticks_within_bucket_update_ohlc():
    agg = CandleAggregator(["M1"])
    agg.apply_tick(_tick(0, 2400.0))
    agg.apply_tick(_tick(10, 2405.0))
    events = agg.apply_tick(_tick(20, 2398.0))

    candle = events[0].candle
    assert candle.open == 2400.0
    assert candle.high == 2405.0
    assert candle.low == 2398.0
    assert candle.close == 2398.0
    assert events[0].closed is False


def test_bucket_crossing_closes_and_opens_new_candle():
    agg = CandleAggregator(["M1"])
    agg.apply_tick(_tick(0, 2400.0))
    agg.apply_tick(_tick(30, 2410.0))
    events = agg.apply_tick(_tick(65, 2420.0))  # crosses into the next minute

    assert len(events) == 2
    closed_event, opened_event = events
    assert closed_event.closed is True
    assert closed_event.candle.close == 2410.0
    assert opened_event.closed is False
    assert opened_event.candle.open == opened_event.candle.close == 2420.0


def test_multiple_granularities_tracked_independently():
    agg = CandleAggregator(["M1", "M5"])
    events = agg.apply_tick(_tick(0, 2400.0))

    assert {e.granularity for e in events} == {"M1", "M5"}


def test_m5_bucket_does_not_close_on_m1_boundary():
    agg = CandleAggregator(["M1", "M5"])
    agg.apply_tick(_tick(0, 2400.0))
    events = agg.apply_tick(_tick(65, 2410.0))  # crosses M1 boundary, not M5

    m1_events = [e for e in events if e.granularity == "M1"]
    m5_events = [e for e in events if e.granularity == "M5"]

    # M1 crossed its bucket boundary: the old bucket closes with its own last
    # price (2400.0 — the only tick it ever saw), a new bucket opens at 2410.0.
    assert [e.closed for e in m1_events] == [True, False]
    assert m1_events[0].candle.close == 2400.0
    assert m1_events[1].candle.open == 2410.0

    # M5 is still in the same bucket: a single in-progress update
    assert len(m5_events) == 1
    assert m5_events[0].closed is False
    assert m5_events[0].candle.high == 2410.0
