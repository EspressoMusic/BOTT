import json

from fastapi import APIRouter, Query
from sqlmodel import select

from app.db import get_session
from app.models import ThoughtLog
from app.timeutil import to_epoch

router = APIRouter()


@router.get("/api/thoughts")
async def get_thoughts(limit: int = Query(50, ge=1, le=500)):
    with get_session() as session:
        rows = session.exec(
            select(ThoughtLog).order_by(ThoughtLog.id.desc()).limit(limit)
        ).all()
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
            }
            for row in rows
        ]
    }
