"""R1 source diversity gate per docs/SCHEMA.md.

Passes only when all hold:
1. At least strategy.min_verified_sources sources with tier other than UNVERIFIED
2. At least strategy.min_primary_records with tier in TIER_A_SOURCE_TIERS
   (PRIMARY_RECORD or CONTEMPORANEOUS) -- CLAUDE.md's own R1 names "contemporaneous
   news archive" as an example of a primary/public record; this used to check
   PRIMARY_RECORD alone, the one place in the codebase these two tiers diverged.
   See docs/SCHEMA.md for the drift this corrects.
3. At least strategy.min_distinct_domains distinct domain values among them (independence)

The gate's structure -- three named conditions, not a single opaque bool --
is shared code, reused by every strategy unchanged. Only the numeric
thresholds vary, and they're read from the subject's own Strategy row, not
from a strategy-specific implementation. See docs/SCHEMA.md for why gate
thresholds are strategy *data* while eligibility scoring is strategy *code*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from sqlmodel import Session, select

from packages.db.models import Source, Strategy, Subject
from packages.db.session import get_session
from packages.domain.enums import TIER_A_SOURCE_TIERS, SourceTier
from packages.research.dispatch import UnknownStrategyError


class UnknownSubjectError(Exception):
    def __init__(self, subject_id: int) -> None:
        self.subject_id = subject_id
        super().__init__(f"unknown subject: {subject_id!r}")


class SourceGateFailureReason(StrEnum):
    INSUFFICIENT_VERIFIED_SOURCES = "insufficient_verified_sources"
    MISSING_TIER_A_SOURCE = "missing_tier_a_source"
    INSUFFICIENT_DISTINCT_DOMAINS = "insufficient_distinct_domains"


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[SourceGateFailureReason] = field(default_factory=list)
    verified_source_count: int = 0
    tier_a_source_count: int = 0
    distinct_domain_count: int = 0


def check_source_gate(subject_id: int, session: Session | None = None) -> GateResult:
    owns_session = session is None
    active_session = session if session is not None else get_session()
    try:
        subject = active_session.get(Subject, subject_id)
        if subject is None:
            raise UnknownSubjectError(subject_id)

        strategy = active_session.get(Strategy, subject.strategy_id)
        if strategy is None:
            raise UnknownStrategyError(subject.strategy_id)

        sources = list(
            active_session.exec(
                select(Source).where(
                    Source.subject_id == subject_id,
                    Source.tier != SourceTier.UNVERIFIED,
                )
            )
        )
    finally:
        if owns_session:
            active_session.close()

    verified_count = len(sources)
    tier_a_count = sum(1 for s in sources if s.tier in TIER_A_SOURCE_TIERS)
    distinct_domains = {s.domain for s in sources}

    reasons: list[SourceGateFailureReason] = []
    if verified_count < strategy.min_verified_sources:
        reasons.append(SourceGateFailureReason.INSUFFICIENT_VERIFIED_SOURCES)
    if tier_a_count < strategy.min_primary_records:
        reasons.append(SourceGateFailureReason.MISSING_TIER_A_SOURCE)
    if len(distinct_domains) < strategy.min_distinct_domains:
        reasons.append(SourceGateFailureReason.INSUFFICIENT_DISTINCT_DOMAINS)

    return GateResult(
        passed=not reasons,
        reasons=reasons,
        verified_source_count=verified_count,
        tier_a_source_count=tier_a_count,
        distinct_domain_count=len(distinct_domains),
    )
