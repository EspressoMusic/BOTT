from datetime import datetime, timezone

from app.timeutil import trading_day_start_utc, trading_day_str


def test_trading_day_before_session_open_belongs_to_previous_day():
    just_before_open = datetime(2026, 8, 13, 7, 59, tzinfo=timezone.utc)
    assert trading_day_start_utc(just_before_open) == datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)
    assert trading_day_str(just_before_open) == "2026-08-12"


def test_trading_day_at_session_open_starts_the_new_day():
    at_open = datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    assert trading_day_start_utc(at_open) == datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    assert trading_day_str(at_open) == "2026-08-13"


def test_trading_day_after_session_open_stays_on_the_same_day():
    mid_afternoon = datetime(2026, 8, 13, 15, 30, tzinfo=timezone.utc)
    assert trading_day_start_utc(mid_afternoon) == datetime(2026, 8, 13, 8, 0, tzinfo=timezone.utc)
    assert trading_day_str(mid_afternoon) == "2026-08-13"
