from fastapi import APIRouter, Request

from app.settings_store import is_bot_enabled, set_setting
from app.trade_stats import todays_realized_pnl

router = APIRouter()


@router.post("/api/bot/enable")
async def enable_bot():
    set_setting("bot_enabled", "true")
    set_setting("auto_stop_message", "")
    return {"bot_enabled": True}


@router.post("/api/bot/disable")
async def disable_bot():
    set_setting("bot_enabled", "false")
    return {"bot_enabled": False}


@router.post("/api/bot/direction-bias/clear")
async def clear_direction_bias(request: Request):
    """Manual escape hatch for the chat-set direction bias (see
    order_service.handle_signal) — lets the user cancel it from the UI
    without having to go back into the chat."""
    set_setting("chat_direction_bias", "")
    await request.app.state.ws_manager.broadcast({"type": "bot_status", "payload": {"direction_bias": None}})
    return {"chat_direction_bias": None}


@router.get("/api/bot/status")
async def bot_status(request: Request):
    execution_broker = request.app.state.execution_broker
    account = await execution_broker.get_account_state()
    open_trades = await execution_broker.get_open_trades()
    return {
        "bot_enabled": is_bot_enabled(),
        "today_pnl": round(todays_realized_pnl(), 2),
        "account": {
            "balance": account.balance,
            "unrealized_pnl": account.unrealized_pnl,
            "open_trade_count": account.open_trade_count,
        },
        "open_trades": [
            {
                "broker_trade_id": t.broker_trade_id,
                "instrument": t.instrument,
                "side": t.side,
                "units": t.units,
                "entry_price": t.entry_price,
                "unrealized_pnl": t.unrealized_pnl,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
            }
            for t in open_trades
        ],
    }
