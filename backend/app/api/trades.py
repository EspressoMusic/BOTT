from fastapi import APIRouter, HTTPException, Query, Request
from sqlmodel import select

from app.db import get_session
from app.models import Trade
from app.timeutil import to_epoch

router = APIRouter()


def _trade_dict(trade: Trade) -> dict:
    return {
        "id": trade.id,
        "instrument": trade.instrument,
        "side": trade.side,
        "status": trade.status,
        "entry_price": trade.entry_price,
        "entry_time": to_epoch(trade.entry_time),
        "exit_price": trade.exit_price,
        "exit_time": to_epoch(trade.exit_time) if trade.exit_time else None,
        "exit_reason": trade.exit_reason,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "units": trade.units,
        "pnl": trade.pnl,
        "strategy_id": trade.strategy_id,
        "signal_reason": trade.signal_reason,
    }


@router.get("/api/trades")
async def list_trades(
    status: str | None = Query(None),
    instrument: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    with get_session() as session:
        query = select(Trade).order_by(Trade.id.desc()).limit(limit)
        if status:
            query = query.where(Trade.status == status.upper())
        if instrument:
            query = query.where(Trade.instrument == instrument)
        rows = session.exec(query).all()
    rows.reverse()
    return {"trades": [_trade_dict(t) for t in rows]}


@router.post("/api/positions/{trade_id}/close")
async def close_position(trade_id: int, request: Request):
    order_service = request.app.state.order_service
    ok = await order_service.close_position_manually(trade_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not close position (not found or not open)")
    return {"status": "closed"}


@router.patch("/api/positions/{trade_id}/modify")
async def modify_position(trade_id: int, request: Request):
    body = await request.json()
    stop_loss = body.get("stop_loss")
    take_profit = body.get("take_profit")
    order_service = request.app.state.order_service
    ok = await order_service.modify_position_manually(trade_id, stop_loss, take_profit)
    if not ok:
        raise HTTPException(status_code=400, detail="Could not modify position (not found or not open)")
    return {"status": "modified"}
