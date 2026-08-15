from app.ai_chat import build_context


def test_build_context_includes_recent_closed_trades_and_reason():
    context = build_context(
        zone=None,
        trade=None,
        recent_candles=[],
        recent_thoughts=[],
        active_strategy="scalping",
        recent_trades=[
            {
                "side": "BUY",
                "entry_price": 2400.0,
                "exit_price": 2390.0,
                "exit_reason": "SL",
                "pnl": -100.0,
                "strategy_id": "scalping",
                "signal_reason": "EMA crossover up",
                "time": 1_700_000_000,
            },
            {
                "side": "SELL",
                "entry_price": 2401.0,
                "exit_price": 2411.0,
                "exit_reason": "SL",
                "pnl": -100.0,
                "strategy_id": "scalping",
                "signal_reason": "EMA crossover down",
                "time": 1_700_000_600,
            },
        ],
        open_trades=None,
    )
    assert "עסקאות אחרונות שנסגרו" in context
    assert "סטופ לוס" in context
    assert "EMA crossover up" in context
    assert "-100.00$" in context


def test_build_context_includes_open_trades():
    context = build_context(
        zone=None,
        trade=None,
        recent_candles=[],
        recent_thoughts=[],
        active_strategy="scalping",
        recent_trades=None,
        open_trades=[{"side": "BUY", "entry_price": 2400.0, "stop_loss": 2390.0, "take_profit": 2420.0}],
    )
    assert "עסקאות פתוחות כרגע" in context
    assert "2400.00" in context


def test_build_context_mentions_active_direction_bias():
    context = build_context(
        zone=None,
        trade=None,
        recent_candles=[],
        recent_thoughts=[],
        active_strategy="scalping",
        direction_bias="BUY",
    )
    assert "חוסם כרגע איתותים שאינם קנייה" in context


def test_build_context_omits_empty_sections():
    context = build_context(
        zone=None,
        trade=None,
        recent_candles=[],
        recent_thoughts=[],
        active_strategy="scalping",
    )
    assert "עסקאות אחרונות שנסגרו" not in context
    assert "עסקאות פתוחות כרגע" not in context
