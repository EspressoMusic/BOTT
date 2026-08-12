"""Key/value app settings persisted in SQLite (bot_enabled, active_strategy_id,
risk params, ...). Separate from app/config.py, which holds process-startup
config (API keys, data source) loaded once from .env — these are settings the
user changes at runtime from the Settings screen.
"""

from sqlmodel import select

from app.db import get_session
from app.models import AppSetting

DEFAULTS = {
    "bot_enabled": "true",
    "active_strategy_id": "scalping",
    "risk_units": "10",
    "max_concurrent_positions": "1",
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
    with get_session() as session:
        rows = session.exec(select(AppSetting)).all()
    merged = dict(DEFAULTS)
    merged.update({row.key: row.value for row in rows})
    return merged


def is_bot_enabled() -> bool:
    return get_setting("bot_enabled").lower() == "true"
