"""Read-only. Strategies are created by migration/seed, not through the API --
see the note on Strategy in packages/db/models.py for why there's no
create/update endpoint here.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from sqlmodel import select

from apps.api.deps import SessionDep, get_strategy_or_404
from apps.api.schemas import StrategyRead
from packages.db.models import Strategy
from packages.research.dispatch import StrategyDefinition, get_strategy_definition

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic's model_json_schema() puts enum fields behind a $ref into
    $defs. Resolve them here so a client can read attributes_schema without
    its own JSON-schema resolver."""
    defs = schema.get("$defs", {})
    properties = {}
    for name, prop in schema.get("properties", {}).items():
        ref = prop.get("$ref")
        properties[name] = defs[ref.removeprefix("#/$defs/")] if ref else prop
    return {
        "title": schema.get("title", ""),
        "properties": properties,
        "required": schema.get("required", []),
    }


def _to_strategy_read(strategy: Strategy, definition: StrategyDefinition[Any]) -> StrategyRead:
    return StrategyRead(
        id=strategy.id,  # type: ignore[arg-type]  # always set once persisted
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
        slug=strategy.slug,
        name=strategy.name,
        description=strategy.description,
        subject_noun_singular=strategy.subject_noun_singular,
        subject_noun_plural=strategy.subject_noun_plural,
        min_verified_sources=strategy.min_verified_sources,
        min_primary_records=strategy.min_primary_records,
        min_distinct_domains=strategy.min_distinct_domains,
        style_guide=strategy.style_guide,
        allowed_archive_providers=strategy.allowed_archive_providers,
        is_active=strategy.is_active,
        risk_flags=[flag.value for flag in definition.risk_flag_enum],
        attributes_schema=_inline_refs(definition.attributes_model.model_json_schema()),
    )


@router.get("", response_model=list[StrategyRead])
def list_strategies(session: SessionDep) -> list[StrategyRead]:
    strategies = session.exec(select(Strategy))
    return [
        _to_strategy_read(strategy, get_strategy_definition(strategy.slug))
        for strategy in strategies
    ]


@router.get("/{slug}", response_model=StrategyRead)
def get_strategy(slug: str, session: SessionDep) -> StrategyRead:
    strategy = get_strategy_or_404(session, slug)
    return _to_strategy_read(strategy, get_strategy_definition(slug))
