"""CRUD for structured feedback rules — the ones that actually constrain the bot
(see app/feedback_rules.py for where they're enforced, in OrderService).
"""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import select

from app.db import get_session
from app.models import FeedbackRule

router = APIRouter()


class FeedbackRuleCreate(BaseModel):
    description: str
    conditions: dict
    action: str = "block_entry"
    side_filter: str | None = None


class FeedbackRuleUpdate(BaseModel):
    is_active: bool | None = None
    description: str | None = None
    conditions: dict | None = None
    side_filter: str | None = None


def _rule_dict(rule: FeedbackRule) -> dict:
    return {
        "id": rule.id,
        "description": rule.description,
        "conditions": json.loads(rule.conditions_json),
        "action": rule.action,
        "side_filter": rule.side_filter,
        "is_active": rule.is_active,
    }


@router.get("/api/feedback-rules")
async def list_feedback_rules():
    with get_session() as session:
        rules = session.exec(select(FeedbackRule).order_by(FeedbackRule.id.desc())).all()
    return {"rules": [_rule_dict(r) for r in rules]}


@router.post("/api/feedback-rules")
async def create_feedback_rule(body: FeedbackRuleCreate):
    with get_session() as session:
        rule = FeedbackRule(
            description=body.description,
            conditions_json=json.dumps(body.conditions),
            action=body.action,
            side_filter=body.side_filter,
            is_active=True,
        )
        session.add(rule)
        session.commit()
        session.refresh(rule)
        result = _rule_dict(rule)
    return result


@router.put("/api/feedback-rules/{rule_id}")
async def update_feedback_rule(rule_id: int, body: FeedbackRuleUpdate):
    with get_session() as session:
        rule = session.get(FeedbackRule, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Rule not found")
        if body.is_active is not None:
            rule.is_active = body.is_active
        if body.description is not None:
            rule.description = body.description
        if body.conditions is not None:
            rule.conditions_json = json.dumps(body.conditions)
        if body.side_filter is not None:
            rule.side_filter = body.side_filter
        session.add(rule)
        session.commit()
        session.refresh(rule)
        result = _rule_dict(rule)
    return result


@router.delete("/api/feedback-rules/{rule_id}")
async def delete_feedback_rule(rule_id: int):
    with get_session() as session:
        rule = session.get(FeedbackRule, rule_id)
        if rule is None:
            raise HTTPException(status_code=404, detail="Rule not found")
        session.delete(rule)
        session.commit()
    return {"status": "deleted"}
