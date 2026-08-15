import json

from fastapi import APIRouter, Query
from sqlmodel import select

from app.db import get_session
from app.models import ThoughtLog
from app.timeutil import to_epoch

router = APIRouter()


@router.get("/api/thoughts")
async def get_thoughts(limit: int = Query(50, ge=1, le=500), instrument: str | None = Query(None)):
    with get_session() as session:
        query = select(ThoughtLog).order_by(ThoughtLog.id.desc()).limit(limit)
        if instrument:
            # Rows written before multi-instrument switching existed have "" —
            # excluded here same as any other instrument that doesn't match.
            query = query.where(ThoughtLog.instrument == instrument)
        rows = session.exec(query).all()
    rows.reverse()

    return {
        "thoughts": [
            {
                "id": row.id,
                "time": to_epoch(row.timestamp),
                "candle_time": to_epoch(row.candle_time),
                "text": row.text,
                "signal": row.signal,
                "indicators": json.loads(row.indicators_json),
                "instrument": row.instrument,
            }
            for row in rows
        ]
    }
