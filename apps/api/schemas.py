"""API request/response models.

These are deliberately separate from the SQLModel tables in packages/db/models.py.
CaseCreate and CaseUpdate do not have monetization_tier, legal_risk, or
eligibility_notes as fields at all -- the API is structurally incapable of
accepting a client-supplied override for values the before_insert/before_update
listeners (packages/db/listeners.py) compute unconditionally. `extra="forbid"`
turns an attempt to sneak one in via the request body into a 422, not a
silent no-op.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from packages.domain.enums import (
    CaseStatus,
    CaseType,
    LegalRisk,
    MonetizationTier,
    ResolutionStatus,
    RiskFlag,
    SourceTier,
)
from packages.research.gate import SourceGateFailureReason


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str
    case_type: CaseType
    event_year: int
    country: str
    region: str | None = None
    summary: str
    resolution_status: ResolutionStatus
    living_persons_involved: bool = False
    risk_flags: list[RiskFlag] = []
    documentation_score: int | None = None
    estimated_runtime_min: int | None = None
    status: CaseStatus = CaseStatus.CANDIDATE
    rejected_reason: str | None = None


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = None
    title: str | None = None
    case_type: CaseType | None = None
    event_year: int | None = None
    country: str | None = None
    region: str | None = None
    summary: str | None = None
    resolution_status: ResolutionStatus | None = None
    living_persons_involved: bool | None = None
    risk_flags: list[RiskFlag] | None = None
    documentation_score: int | None = None
    estimated_runtime_min: int | None = None
    status: CaseStatus | None = None
    rejected_reason: str | None = None


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    slug: str
    title: str
    case_type: CaseType
    event_year: int
    country: str
    region: str | None
    summary: str
    resolution_status: ResolutionStatus
    living_persons_involved: bool
    risk_flags: list[RiskFlag]
    documentation_score: int | None
    estimated_runtime_min: int | None
    monetization_tier: MonetizationTier
    legal_risk: LegalRisk
    eligibility_notes: list[str]
    status: CaseStatus
    rejected_reason: str | None


class CaseListResponse(BaseModel):
    items: list[CaseRead]
    total: int
    offset: int
    limit: int


class EligibilityResultRead(BaseModel):
    tier: MonetizationTier
    legal_risk: LegalRisk
    notes: list[str]


class GateResultRead(BaseModel):
    passed: bool
    reasons: list[SourceGateFailureReason]
    verified_source_count: int
    primary_record_count: int
    distinct_domain_count: int


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    publisher: str
    title: str
    published_date: date | None = None
    retrieved_at: datetime | None = None
    tier: SourceTier
    text_path: str
    text_sha256: str
    word_count: int


class SourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    case_id: int
    url: str
    domain: str
    publisher: str
    title: str
    published_date: date | None
    retrieved_at: datetime
    tier: SourceTier
    text_path: str
    text_sha256: str
    word_count: int
