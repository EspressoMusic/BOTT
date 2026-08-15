from app.settings_store import get_setting, is_bot_enabled, set_setting
from app.timeutil import trading_day_str


def test_is_bot_enabled_clears_stale_daily_stop_on_a_new_trading_day():
    set_setting("bot_enabled", "false")
    set_setting("daily_stop_date", "2000-01-01")  # clearly a past trading day

    assert is_bot_enabled() is True
    assert get_setting("daily_stop_date") == ""


def test_is_bot_enabled_keeps_daily_stop_for_the_same_trading_day():
    set_setting("bot_enabled", "false")
    set_setting("daily_stop_date", trading_day_str())

    assert is_bot_enabled() is False
    assert get_setting("daily_stop_date") == trading_day_str()

    set_setting("bot_enabled", "true")
    set_setting("daily_stop_date", "")
