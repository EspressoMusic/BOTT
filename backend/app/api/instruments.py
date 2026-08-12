from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.instruments import AVAILABLE_INSTRUMENTS, instrument_label

router = APIRouter()


class InstrumentSwitch(BaseModel):
    instrument: str


@router.get("/api/instruments")
async def list_instruments(request: Request):
    active = request.app.state.instrument
    if request.app.state.supports_instrument_switch:
        available = [{"id": i.id, "label": i.label} for i in AVAILABLE_INSTRUMENTS]
    else:
        # Data source doesn't honor a runtime instrument switch — offer only
        # the one it's actually serving, so the picker doesn't lie.
        available = [{"id": active, "label": instrument_label(active)}]
    return {"active": active, "active_label": instrument_label(active), "available": available}


@router.post("/api/instrument")
async def switch_instrument(body: InstrumentSwitch, request: Request):
    if not request.app.state.supports_instrument_switch:
        raise HTTPException(status_code=400, detail="החלפת נכס לא נתמכת עם מקור הנתונים הנוכחי")

    valid_ids = {i.id for i in AVAILABLE_INSTRUMENTS}
    if body.instrument not in valid_ids:
        raise HTTPException(status_code=400, detail=f"נכס לא מוכר: {body.instrument!r}")

    if body.instrument == request.app.state.instrument:
        return {"instrument": request.app.state.instrument, "label": instrument_label(request.app.state.instrument)}

    open_trades = await request.app.state.execution_broker.get_open_trades()
    if open_trades:
        raise HTTPException(status_code=409, detail="לא ניתן להחליף נכס כשיש פוזיציה פתוחה — סגרו אותה קודם")

    await request.app.state.switch_instrument(body.instrument)
    return {"instrument": request.app.state.instrument, "label": instrument_label(request.app.state.instrument)}
