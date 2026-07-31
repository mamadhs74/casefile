"""Case CRUD, listing, and the DB-free eligibility preview."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func
from sqlmodel import select

from apps.api.deps import SessionDep, get_case_or_404
from apps.api.schemas import (
    CaseCreate,
    CaseListResponse,
    CaseRead,
    CaseUpdate,
    EligibilityResultRead,
)
from packages.db.models import Case
from packages.domain.enums import CaseStatus, CaseType, MonetizationTier
from packages.research.eligibility import score_case

router = APIRouter(prefix="/cases", tags=["cases"])


@router.post("/preview-eligibility", response_model=EligibilityResultRead)
def preview_eligibility(payload: CaseCreate) -> EligibilityResultRead:
    """Score a not-yet-persisted case. Touches no DB."""
    result = score_case(payload)
    return EligibilityResultRead(tier=result.tier, legal_risk=result.legal_risk, notes=result.notes)


@router.get("", response_model=CaseListResponse)
def list_cases(
    session: SessionDep,
    status: Annotated[CaseStatus | None, Query()] = None,
    monetization_tier: Annotated[MonetizationTier | None, Query()] = None,
    case_type: Annotated[CaseType | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CaseListResponse:
    query = select(Case)
    count_query = select(func.count()).select_from(Case)
    if status is not None:
        query = query.where(Case.status == status)
        count_query = count_query.where(Case.status == status)
    if monetization_tier is not None:
        query = query.where(Case.monetization_tier == monetization_tier)
        count_query = count_query.where(Case.monetization_tier == monetization_tier)
    if case_type is not None:
        query = query.where(Case.case_type == case_type)
        count_query = count_query.where(Case.case_type == case_type)

    total = session.execute(count_query).scalar_one()
    items = list(session.exec(query.offset(offset).limit(limit)))
    return CaseListResponse(
        items=[CaseRead.model_validate(case) for case in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("", response_model=CaseRead, status_code=201)
def create_case(payload: CaseCreate, session: SessionDep) -> CaseRead:
    case = Case(**payload.model_dump())
    session.add(case)
    session.commit()
    session.refresh(case)
    return CaseRead.model_validate(case)


@router.get("/{case_id}", response_model=CaseRead)
def get_case(case_id: int, session: SessionDep) -> CaseRead:
    case = get_case_or_404(session, case_id)
    return CaseRead.model_validate(case)


@router.patch("/{case_id}", response_model=CaseRead)
def update_case(case_id: int, payload: CaseUpdate, session: SessionDep) -> CaseRead:
    case = get_case_or_404(session, case_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(case, field, value)
    session.add(case)
    session.commit()
    session.refresh(case)
    return CaseRead.model_validate(case)


@router.delete("/{case_id}", status_code=204)
def delete_case(case_id: int, session: SessionDep) -> None:
    case = get_case_or_404(session, case_id)
    session.delete(case)
    session.commit()
