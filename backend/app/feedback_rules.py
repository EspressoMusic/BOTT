"""Structured, DB-backed rules that actually change bot behavior — distinct from
free-text journal notes (app/api/journal.py), which are display-only history.
Evaluated by OrderService before every trade, against the same indicator
snapshot the strategy just computed (e.g. "don't buy when RSI > 70").
"""

from __future__ import annotations

import json

from sqlmodel import select

from app.condition_dsl import evaluate_condition
from app.db import get_session
from app.models import FeedbackRule

_BLOCKING_ACTIONS = {"block_entry", "block_side"}


def evaluate_feedback_rules(action: str, indicators: dict[str, float]) -> FeedbackRule | None:
    """Returns the first active rule that blocks this signal, or None if allowed."""
    with get_session() as session:
        rules = session.exec(select(FeedbackRule).where(FeedbackRule.is_active == True)).all()  # noqa: E712

    for rule in rules:
        if rule.action not in _BLOCKING_ACTIONS:
            continue
        if rule.side_filter and rule.side_filter != action:
            continue
        conditions = json.loads(rule.conditions_json)
        if evaluate_condition(conditions, indicators):
            return rule
    return None
