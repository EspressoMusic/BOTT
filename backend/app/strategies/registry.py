"""Registry of built-in strategies, keyed by id. Custom (user-defined) strategies
aren't pre-registered here — they're constructed on demand from their
StrategyConfig row via `create_custom_strategy`.
"""

from __future__ import annotations

import json

from app.models import StrategyConfig
from app.strategies.atr_trend_following import AtrTrendFollowingStrategy
from app.strategies.base import Strategy
from app.strategies.bollinger_breakout import BollingerBreakoutStrategy
from app.strategies.macd_trend import MacdTrendStrategy
from app.strategies.moving_average import MovingAverageCrossoverStrategy
from app.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from app.strategies.rule_based import RuleBasedStrategy
from app.strategies.scalping import ScalpingStrategy

BUILTIN_STRATEGY_CLASSES = {
    ScalpingStrategy.id: ScalpingStrategy,
    MovingAverageCrossoverStrategy.id: MovingAverageCrossoverStrategy,
    RsiMeanReversionStrategy.id: RsiMeanReversionStrategy,
    MacdTrendStrategy.id: MacdTrendStrategy,
    BollingerBreakoutStrategy.id: BollingerBreakoutStrategy,
    AtrTrendFollowingStrategy.id: AtrTrendFollowingStrategy,
}


def list_builtin_strategies() -> list[dict]:
    return [{"id": cls.id, "display_name": cls.display_name, "kind": "builtin"} for cls in BUILTIN_STRATEGY_CLASSES.values()]


def create_builtin_strategy(strategy_id: str) -> Strategy | None:
    cls = BUILTIN_STRATEGY_CLASSES.get(strategy_id)
    return cls() if cls else None


def create_strategy_from_config(config: StrategyConfig) -> Strategy | None:
    if config.kind == "builtin":
        return create_builtin_strategy(config.id)
    if config.kind == "custom" and config.dsl_json:
        return RuleBasedStrategy(config.id, config.display_name, json.loads(config.dsl_json))
    return None
