import json

from app.db import get_session
from app.feedback_rules import evaluate_feedback_rules
from app.models import FeedbackRule


def _add_rule(**kwargs) -> None:
    with get_session() as session:
        session.add(FeedbackRule(**kwargs))
        session.commit()


def test_no_matching_rule_allows_the_signal():
    # An indicator key no rule in this test module references — robust regardless
    # of what other tests in this session-scoped DB have already inserted.
    assert evaluate_feedback_rules("BUY", {"unrelated_indicator_xyz": 90}) is None


def test_matching_active_rule_blocks_signal():
    _add_rule(
        description="test: block buy when rsi > 80",
        conditions_json=json.dumps({"left": "rsi", "op": ">", "right": 80}),
        action="block_entry",
        side_filter="BUY",
        is_active=True,
    )
    blocked = evaluate_feedback_rules("BUY", {"rsi": 85})
    assert blocked is not None
    assert "block buy when rsi" in blocked.description


def test_inactive_rule_does_not_block():
    _add_rule(
        description="test: inactive rule",
        conditions_json=json.dumps({"left": "rsi", "op": ">", "right": 80}),
        action="block_entry",
        side_filter="BUY",
        is_active=False,
    )
    assert evaluate_feedback_rules("BUY", {"rsi": 90}) is None


def test_side_filter_only_blocks_matching_side():
    _add_rule(
        description="test: sell-only block",
        conditions_json=json.dumps({"left": "rsi", "op": "<", "right": 20}),
        action="block_entry",
        side_filter="SELL",
        is_active=True,
    )
    assert evaluate_feedback_rules("BUY", {"rsi": 10}) is None
    assert evaluate_feedback_rules("SELL", {"rsi": 10}) is not None
