"""Subject CRUD, listing, and the DB-free eligibility preview.

Renamed from cases.py -- see docs/SCHEMA.md's "Strategy" section. case_type
is gone as a filter/column: it's strategy-owned now (criminal-cases keeps it
under attributes.case_type), and there's no cross-strategy equivalent to
filter on generically. strategy_slug is the new cross-strategy filter.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func
from sqlmodel import select

from apps.api.deps import SessionDep, get_subject_or_404
from apps.api.schemas import (
    EligibilityResultRead,
    SubjectCreate,
    SubjectListResponse,
    SubjectRead,
    SubjectUpdate,
)
from packages.db.models import Strategy, Subject
from packages.domain.enums import MonetizationTier, SubjectStatus
from packages.research.dispatch import UnknownStrategyError, score_subject

router = APIRouter(prefix="/subjects", tags=["subjects"])


@router.post("/preview-eligibility", response_model=EligibilityResultRead)
def preview_eligibility(payload: SubjectCreate) -> EligibilityResultRead:
    """Score a not-yet-persisted subject. Touches no DB."""
    result = score_subject(payload, payload.strategy_slug)
    return EligibilityResultRead(tier=result.tier, legal_risk=result.legal_risk, notes=result.notes)


@router.get("", response_model=SubjectListResponse)
def list_subjects(
    session: SessionDep,
    status: Annotated[SubjectStatus | None, Query()] = None,
    monetization_tier: Annotated[MonetizationTier | None, Query()] = None,
    strategy_slug: Annotated[str | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> SubjectListResponse:
    query = select(Subject)
    count_query = select(func.count()).select_from(Subject)
    if status is not None:
        query = query.where(Subject.status == status)
        count_query = count_query.where(Subject.status == status)
    if monetization_tier is not None:
        query = query.where(Subject.monetization_tier == monetization_tier)
        count_query = count_query.where(Subject.monetization_tier == monetization_tier)
    if strategy_slug is not None:
        strategy = session.exec(select(Strategy).where(Strategy.slug == strategy_slug)).first()
        if strategy is None:
            return SubjectListResponse(items=[], total=0, offset=offset, limit=limit)
        query = query.where(Subject.strategy_id == strategy.id)
        count_query = count_query.where(Subject.strategy_id == strategy.id)

    total = session.execute(count_query).scalar_one()
    items = list(session.exec(query.offset(offset).limit(limit)))
    return SubjectListResponse(
        items=[SubjectRead.model_validate(item) for item in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=SubjectRead, status_code=201)
def create_subject(payload: SubjectCreate, session: SessionDep) -> SubjectRead:
    strategy = session.exec(select(Strategy).where(Strategy.slug == payload.strategy_slug)).first()
    if strategy is None:
        raise UnknownStrategyError(payload.strategy_slug)

    data = payload.model_dump(exclude={"strategy_slug"})
    subject = Subject(strategy_id=strategy.id, **data)
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return SubjectRead.model_validate(subject)


@router.get("/{subject_id}", response_model=SubjectRead)
def get_subject(subject_id: int, session: SessionDep) -> SubjectRead:
    subject = get_subject_or_404(session, subject_id)
    return SubjectRead.model_validate(subject)


@router.patch("/{subject_id}", response_model=SubjectRead)
def update_subject(subject_id: int, payload: SubjectUpdate, session: SessionDep) -> SubjectRead:
    subject = get_subject_or_404(session, subject_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(subject, field, value)
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return SubjectRead.model_validate(subject)


@router.delete("/{subject_id}", status_code=204)
def delete_subject(subject_id: int, session: SessionDep) -> None:
    subject = get_subject_or_404(session, subject_id)
    session.delete(subject)
    session.commit()
