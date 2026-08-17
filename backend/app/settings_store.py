"""Key/value app settings persisted in SQLite (bot_enabled, active_strategy_id,
risk params, ...). Separate from app/config.py, which holds process-startup
config (API keys, data source) loaded once from .env — these are settings the
user changes at runtime from the Settings screen.
"""

from sqlmodel import select

from app.db import get_session
from app.models import AppSetting
from app.timeutil import trading_day_str

DEFAULTS = {
    "bot_enabled": "true",
    "active_strategy_id": "scalping",
    "risk_units": "10",
    "risk_dollars": "0",  # fixed $ to risk per trade; 0 = disabled. Takes priority over risk_pct.
    "risk_pct": "0",  # % of account balance to risk per trade; 0 = disabled, use risk_units instead
    "max_concurrent_positions": "1",
    "daily_profit_target_pct": "0",  # 0 = disabled
    "daily_stop_date": "",  # trading-day date (YYYY-MM-DD) the kill switch was auto-tripped on
    "chat_direction_bias": "",  # "" | "BUY" | "SELL" — set via chat, see order_service.handle_signal
    # Human-readable reason the LAST auto-stop tripped the kill switch (daily
    # profit target, stale candle history, ...). Persisted (not just broadcast
    # over the WS) so a page opened/reloaded after the fact still explains why
    # the bot is off — a WS push alone only reaches clients connected at the
    # exact moment it fires. Cleared on manual re-enable or the next trading day.
    "auto_stop_message": "",
}


def get_setting(key: str, default: str | None = None) -> str:
    with get_session() as session:
        row = session.get(AppSetting, key)
        if row is not None:
            return row.value
    return default if default is not None else DEFAULTS.get(key, "")


def set_setting(key: str, value: str) -> None:
    with get_session() as session:
        row = session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=value)
        else:
            row.value = value
        session.add(row)
        session.commit()


def get_all_settings() -> dict[str, str]:
    reset_daily_stop_if_new_day()
    with get_session() as session:
        rows = session.exec(select(AppSetting)).all()
    merged = dict(DEFAULTS)
    merged.update({row.key: row.value for row in rows})
    return merged


def trip_auto_stop(message: str) -> None:
    """Disable the bot and record why, in a form that survives a page
    reload/reconnect — used by every automatic (non-user-initiated) kill-switch
    trip (daily profit target, stale candle history on startup, ...)."""
    set_setting("bot_enabled", "false")
    set_setting("auto_stop_message", message)


def reset_daily_stop_if_new_day() -> None:
    """The daily-profit auto-stop (see order_service._check_daily_profit_stop)
    is only meant to pause the bot until the next trading day starts (the next
    London session open, 08:00 UTC — see timeutil.trading_day_str) — once that
    boundary is crossed, clear the marker and flip the switch back on
    automatically."""
    stop_date = get_setting("daily_stop_date")
    if stop_date and stop_date != trading_day_str():
        set_setting("daily_stop_date", "")
        set_setting("bot_enabled", "true")
        set_setting("auto_stop_message", "")


def is_bot_enabled() -> bool:
    reset_daily_stop_if_new_day()
    return get_setting("bot_enabled").lower() == "true"
