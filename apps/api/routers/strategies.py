"""Read-only. Strategies are created by migration/seed, not through the API --
see the note on Strategy in packages/db/models.py for why there's no
create/update endpoint here.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from apps.api.deps import SessionDep
from apps.api.schemas import StrategyRead
from packages.db.models import Strategy

router = APIRouter(prefix="/strategies", tags=["strategies"])


@router.get("", response_model=list[StrategyRead])
def list_strategies(session: SessionDep) -> list[StrategyRead]:
    strategies = session.exec(select(Strategy))
    return [StrategyRead.model_validate(strategy) for strategy in strategies]


@router.get("/{slug}", response_model=StrategyRead)
def get_strategy(slug: str, session: SessionDep) -> StrategyRead:
    strategy = session.exec(select(Strategy).where(Strategy.slug == slug)).first()
    if strategy is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    return StrategyRead.model_validate(strategy)
