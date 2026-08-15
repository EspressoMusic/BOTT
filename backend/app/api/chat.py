import json

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import select

from app import ai_chat
from app.db import get_session
from app.models import ChatMessage, ThoughtLog, Trade
from app.settings_store import get_setting, set_setting
from app.timeutil import to_epoch

router = APIRouter()


class ChatAsk(BaseModel):
    message: str
    zone: dict | None = None  # {start_time, end_time, price_low, price_high}
    trade_id: int | None = None


def _message_dict(msg: ChatMessage) -> dict:
    return {
        "id": msg.id,
        "time": to_epoch(msg.timestamp),
        "role": msg.role,
        "text": msg.text,
        "trade_id": msg.trade_id,
        "zone": json.loads(msg.zone_json) if msg.zone_json else None,
    }


def _execute_chat_tool(name: str, args: dict) -> str:
    """The only place a chat tool call actually touches bot state — see
    ai_chat.ask()'s tool_executor contract. Called with a name/args pair the
    model chose from the schema-validated _TOOLS list, never with free text.
    """
    if name == "set_direction_bias":
        direction = args.get("direction")
        if direction not in ("BUY", "SELL"):
            return "שגיאה: כיוון לא תקין."
        set_setting("chat_direction_bias", direction)
        other_side = "מכירה" if direction == "BUY" else "קנייה"
        wanted_side = "קנייה" if direction == "BUY" else "מכירה"
        return (
            f"בוצע. הבוט יתעלם מאיתותי {other_side} ויחכה לאיתות {wanted_side} הבא — "
            f"ברגע שתיפתח עסקת {wanted_side}, החסימה תתבטל אוטומטית."
        )
    if name == "clear_direction_bias":
        set_setting("chat_direction_bias", "")
        return "בוצע. כל חסימת כיוון בוטלה — הבוט חוזר לפעול רגיל בשני הכיוונים."
    return "פעולה לא מוכרת."


@router.get("/api/chat")
async def list_chat_messages(limit: int = Query(100, ge=1, le=500)):
    with get_session() as session:
        rows = session.exec(select(ChatMessage).order_by(ChatMessage.id.desc()).limit(limit)).all()
    rows.reverse()
    return {"messages": [_message_dict(m) for m in rows]}


@router.post("/api/chat")
async def ask_chat(body: ChatAsk, request: Request):
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message is required")

    trade_dict: dict | None = None
    if body.trade_id is not None:
        with get_session() as session:
            trade = session.get(Trade, body.trade_id)
            if trade is not None:
                trade_dict = {
                    "side": trade.side,
                    "entry_price": trade.entry_price,
                    "stop_loss": trade.stop_loss,
                    "take_profit": trade.take_profit,
                    "status": trade.status,
                    "pnl": trade.pnl,
                }

    broker = request.app.state.broker
    instrument = request.app.state.instrument
    candles = await broker.get_candles(instrument, "M1", 60)
    if body.zone:
        in_zone = [c for c in candles if body.zone["start_time"] <= c.time.timestamp() <= body.zone["end_time"]]
        candles = in_zone or candles[-10:]
    else:
        candles = candles[-10:]
    candle_dicts = [{"low": c.low, "high": c.high, "close": c.close} for c in candles]

    with get_session() as session:
        thought_rows = session.exec(select(ThoughtLog).order_by(ThoughtLog.id.desc()).limit(5)).all()
        closed_rows = session.exec(
            select(Trade).where(Trade.status == "CLOSED").order_by(Trade.id.desc()).limit(15)
        ).all()
        open_rows = session.exec(select(Trade).where(Trade.status == "OPEN").order_by(Trade.id.desc())).all()
        # Prior turns of this same conversation, so the model can handle follow-ups
        # ("why?", "what about the other one?") instead of answering each message
        # in isolation with no memory of what was just discussed.
        history_rows = session.exec(select(ChatMessage).order_by(ChatMessage.id.desc()).limit(20)).all()

    recent_thoughts = [row.text for row in reversed(thought_rows)]
    recent_trades = [
        {
            "side": t.side,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "exit_reason": t.exit_reason,
            "pnl": t.pnl,
            "strategy_id": t.strategy_id,
            "signal_reason": t.signal_reason,
            "time": to_epoch(t.exit_time) if t.exit_time is not None else to_epoch(t.entry_time),
        }
        for t in reversed(closed_rows)
    ]
    open_trades = [
        {"side": t.side, "entry_price": t.entry_price, "stop_loss": t.stop_loss, "take_profit": t.take_profit}
        for t in open_rows
    ]
    history = [{"role": row.role, "content": row.text} for row in reversed(history_rows)]

    active_strategy = get_setting("active_strategy_id")
    direction_bias_before = get_setting("chat_direction_bias", "") or None
    context = ai_chat.build_context(
        body.zone,
        trade_dict,
        candle_dicts,
        recent_thoughts,
        active_strategy,
        recent_trades,
        open_trades,
        direction_bias_before,
    )

    try:
        reply_text = await ai_chat.ask(body.message, context, history, tool_executor=_execute_chat_tool)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {exc}") from exc

    direction_bias_after = get_setting("chat_direction_bias", "") or None
    if direction_bias_after != direction_bias_before:
        await request.app.state.ws_manager.broadcast(
            {"type": "bot_status", "payload": {"direction_bias": direction_bias_after}}
        )

    with get_session() as session:
        user_msg = ChatMessage(
            role="user",
            text=body.message,
            trade_id=body.trade_id,
            zone_json=json.dumps(body.zone) if body.zone else None,
        )
        session.add(user_msg)
        assistant_msg = ChatMessage(role="assistant", text=reply_text, trade_id=body.trade_id)
        session.add(assistant_msg)
        session.commit()
        session.refresh(user_msg)
        session.refresh(assistant_msg)
        result = {"user": _message_dict(user_msg), "assistant": _message_dict(assistant_msg)}

    return result
