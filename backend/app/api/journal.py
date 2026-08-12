"""Free-text notes — display-only history for the user's own reference. Does NOT
change bot behavior (see app/api/feedback_rules.py for the structured rules that
actually do). Can optionally be tied to a specific trade and/or a chart zone the
user dragged out on the price chart.
"""

import json

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlmodel import select

from app.db import get_session
from app.models import JournalNote
from app.timeutil import to_epoch

router = APIRouter()


class JournalNoteCreate(BaseModel):
    note_text: str
    trade_id: int | None = None
    context: dict = {}
    zone: dict | None = None  # {start_time, end_time, price_low, price_high}


def _note_dict(note: JournalNote) -> dict:
    return {
        "id": note.id,
        "trade_id": note.trade_id,
        "time": to_epoch(note.timestamp),
        "note_text": note.note_text,
        "context": json.loads(note.context_json),
        "zone": json.loads(note.zone_json) if note.zone_json else None,
    }


@router.get("/api/journal")
async def list_journal_notes(limit: int = Query(100, ge=1, le=1000)):
    with get_session() as session:
        rows = session.exec(select(JournalNote).order_by(JournalNote.id.desc()).limit(limit)).all()
    rows.reverse()
    return {"notes": [_note_dict(n) for n in rows]}


@router.post("/api/journal")
async def create_journal_note(body: JournalNoteCreate):
    with get_session() as session:
        note = JournalNote(
            trade_id=body.trade_id,
            note_text=body.note_text,
            context_json=json.dumps(body.context),
            zone_json=json.dumps(body.zone) if body.zone else None,
        )
        session.add(note)
        session.commit()
        session.refresh(note)
        result = _note_dict(note)
    return result
