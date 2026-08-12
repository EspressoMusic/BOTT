import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select

from app.db import get_session
from app.models import StrategyConfig
from app.settings_store import set_setting
from app.strategies.registry import (
    BUILTIN_STRATEGY_CLASSES,
    create_builtin_strategy,
    create_strategy_from_config,
    list_builtin_strategies,
)
from app.strategies.rule_based import RuleBasedStrategy

router = APIRouter()


class CustomStrategyCreate(BaseModel):
    display_name: str
    dsl: dict


def _config_dict(config: StrategyConfig) -> dict:
    return {
        "id": config.id,
        "display_name": config.display_name,
        "kind": config.kind,
        "dsl": json.loads(config.dsl_json) if config.dsl_json else None,
    }


@router.get("/api/strategies")
async def list_strategies():
    builtins = list_builtin_strategies()
    with get_session() as session:
        customs = session.exec(select(StrategyConfig).where(StrategyConfig.kind == "custom")).all()
    return {"strategies": builtins + [_config_dict(c) for c in customs]}


@router.post("/api/strategies")
async def create_custom_strategy(body: CustomStrategyCreate):
    strategy_id = f"custom-{uuid.uuid4().hex[:8]}"
    try:
        RuleBasedStrategy(strategy_id, body.display_name, body.dsl)  # validates the DSL constructs cleanly
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"הגדרת אסטרטגיה לא תקינה: {exc}") from exc

    with get_session() as session:
        config = StrategyConfig(
            id=strategy_id, display_name=body.display_name, kind="custom", dsl_json=json.dumps(body.dsl)
        )
        session.add(config)
        session.commit()
        session.refresh(config)
    return _config_dict(config)


@router.delete("/api/strategies/{strategy_id}")
async def delete_custom_strategy(strategy_id: str):
    with get_session() as session:
        config = session.get(StrategyConfig, strategy_id)
        if config is None or config.kind != "custom":
            raise HTTPException(status_code=404, detail="Custom strategy not found")
        session.delete(config)
        session.commit()
    return {"status": "deleted"}


@router.post("/api/strategies/{strategy_id}/activate")
async def activate_strategy(strategy_id: str, request: Request):
    strategy = None
    if strategy_id in BUILTIN_STRATEGY_CLASSES:
        strategy = create_builtin_strategy(strategy_id)
    else:
        with get_session() as session:
            config = session.get(StrategyConfig, strategy_id)
        if config is not None:
            strategy = create_strategy_from_config(config)

    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    request.app.state.strategy_engine.set_strategy(strategy)
    set_setting("active_strategy_id", strategy_id)
    return {"active_strategy_id": strategy_id}
