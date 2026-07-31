"""Sources for a case, and the R1 source-diversity gate."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlmodel import select

from apps.api.deps import SessionDep, get_case_or_404
from apps.api.schemas import GateResultRead, SourceCreate, SourceRead
from packages.db.models import Source
from packages.research.gate import check_source_gate

router = APIRouter(prefix="/cases", tags=["sources"])


@router.get("/{case_id}/sources", response_model=list[SourceRead])
def list_sources(case_id: int, session: SessionDep) -> list[SourceRead]:
    get_case_or_404(session, case_id)
    sources = session.exec(select(Source).where(Source.case_id == case_id))
    return [SourceRead.model_validate(source) for source in sources]


@router.post("/{case_id}/sources", response_model=SourceRead, status_code=201)
def create_source(case_id: int, payload: SourceCreate, session: SessionDep) -> SourceRead:
    get_case_or_404(session, case_id)
    source = Source(
        case_id=case_id,
        retrieved_at=payload.retrieved_at or datetime.now(UTC),
        **payload.model_dump(exclude={"retrieved_at"}),
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    return SourceRead.model_validate(source)


@router.get("/{case_id}/gate", response_model=GateResultRead)
def get_source_gate(case_id: int, session: SessionDep) -> GateResultRead:
    get_case_or_404(session, case_id)
    result = check_source_gate(case_id, session=session)
    return GateResultRead(
        passed=result.passed,
        reasons=result.reasons,
        verified_source_count=result.verified_source_count,
        primary_record_count=result.primary_record_count,
        distinct_domain_count=result.distinct_domain_count,
    )
