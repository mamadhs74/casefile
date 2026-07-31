"""R1 source diversity gate per docs/SCHEMA.md.

Passes only when all hold:
1. At least 3 sources with tier other than UNVERIFIED
2. At least 1 with tier PRIMARY_RECORD
3. At least 3 distinct domain values among them (independence)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from sqlmodel import Session, select

from packages.db.models import Source, SourceTier
from packages.db.session import get_session

MIN_VERIFIED_SOURCES = 3
MIN_DISTINCT_DOMAINS = 3


class SourceGateFailureReason(StrEnum):
    INSUFFICIENT_VERIFIED_SOURCES = "insufficient_verified_sources"
    MISSING_PRIMARY_RECORD = "missing_primary_record"
    INSUFFICIENT_DISTINCT_DOMAINS = "insufficient_distinct_domains"


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[SourceGateFailureReason] = field(default_factory=list)
    verified_source_count: int = 0
    primary_record_count: int = 0
    distinct_domain_count: int = 0


def check_source_gate(case_id: int, session: Session | None = None) -> GateResult:
    owns_session = session is None
    active_session = session if session is not None else get_session()
    try:
        sources = list(
            active_session.exec(
                select(Source).where(
                    Source.case_id == case_id,
                    Source.tier != SourceTier.UNVERIFIED,
                )
            )
        )
    finally:
        if owns_session:
            active_session.close()

    verified_count = len(sources)
    primary_count = sum(1 for s in sources if s.tier == SourceTier.PRIMARY_RECORD)
    distinct_domains = {s.domain for s in sources}

    reasons: list[SourceGateFailureReason] = []
    if verified_count < MIN_VERIFIED_SOURCES:
        reasons.append(SourceGateFailureReason.INSUFFICIENT_VERIFIED_SOURCES)
    if primary_count < 1:
        reasons.append(SourceGateFailureReason.MISSING_PRIMARY_RECORD)
    if len(distinct_domains) < MIN_DISTINCT_DOMAINS:
        reasons.append(SourceGateFailureReason.INSUFFICIENT_DISTINCT_DOMAINS)

    return GateResult(
        passed=not reasons,
        reasons=reasons,
        verified_source_count=verified_count,
        primary_record_count=primary_count,
        distinct_domain_count=len(distinct_domains),
    )
