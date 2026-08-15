from app.api.chat import _execute_chat_tool
from app.settings_store import get_setting


def test_set_direction_bias_stores_valid_direction():
    result = _execute_chat_tool("set_direction_bias", {"direction": "BUY"})
    assert get_setting("chat_direction_bias") == "BUY"
    assert "קנייה" in result or "BUY" in result


def test_set_direction_bias_rejects_invalid_direction():
    _execute_chat_tool("set_direction_bias", {"direction": "UP"})
    assert get_setting("chat_direction_bias") == ""


def test_clear_direction_bias_resets_setting():
    _execute_chat_tool("set_direction_bias", {"direction": "SELL"})
    assert get_setting("chat_direction_bias") == "SELL"

    _execute_chat_tool("clear_direction_bias", {})
    assert get_setting("chat_direction_bias") == ""


def test_unknown_tool_name_is_a_no_op():
    result = _execute_chat_tool("delete_everything", {})
    assert get_setting("chat_direction_bias") == ""
    assert "לא מוכר" in result
