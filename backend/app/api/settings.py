from fastapi import APIRouter
from pydantic import BaseModel

from app.settings_store import get_all_settings, set_setting

router = APIRouter()


class SettingsUpdate(BaseModel):
    risk_units: float | None = None
    max_concurrent_positions: int | None = None
    daily_profit_target_pct: float | None = None


@router.get("/api/settings")
async def get_settings():
    return get_all_settings()


@router.put("/api/settings")
async def update_settings(update: SettingsUpdate):
    if update.risk_units is not None:
        set_setting("risk_units", str(update.risk_units))
    if update.max_concurrent_positions is not None:
        set_setting("max_concurrent_positions", str(update.max_concurrent_positions))
    if update.daily_profit_target_pct is not None:
        set_setting("daily_profit_target_pct", str(update.daily_profit_target_pct))
    return get_all_settings()
