"""Sources for a subject, and the R1 source-diversity gate."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from sqlmodel import select

from apps.api.deps import SessionDep, get_subject_or_404
from apps.api.schemas import GateResultRead, SourceCreate, SourceRead
from packages.db.models import Source
from packages.research.gate import check_source_gate

router = APIRouter(prefix="/subjects", tags=["sources"])


@router.get("/{subject_id}/sources", response_model=list[SourceRead])
def list_sources(subject_id: int, session: SessionDep) -> list[SourceRead]:
    get_subject_or_404(session, subject_id)
    sources = session.exec(select(Source).where(Source.subject_id == subject_id))
    return [SourceRead.model_validate(source) for source in sources]


@router.post("/{subject_id}/sources", response_model=SourceRead, status_code=201)
def create_source(subject_id: int, payload: SourceCreate, session: SessionDep) -> SourceRead:
    get_subject_or_404(session, subject_id)
    source = Source(
        subject_id=subject_id,
        retrieved_at=payload.retrieved_at or datetime.now(UTC),
        **payload.model_dump(exclude={"retrieved_at"}),
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    return SourceRead.model_validate(source)


@router.get("/{subject_id}/gate", response_model=GateResultRead)
def get_source_gate(subject_id: int, session: SessionDep) -> GateResultRead:
    get_subject_or_404(session, subject_id)
    result = check_source_gate(subject_id, session=session)
    return GateResultRead(
        passed=result.passed,
        reasons=result.reasons,
        verified_source_count=result.verified_source_count,
        tier_a_source_count=result.tier_a_source_count,
        distinct_domain_count=result.distinct_domain_count,
    )
