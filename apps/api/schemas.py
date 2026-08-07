"""API request/response models.

These are deliberately separate from the SQLModel tables in packages/db/models.py.
SubjectCreate and SubjectUpdate do not have monetization_tier, legal_risk, or
eligibility_notes as fields at all -- the API is structurally incapable of
accepting a client-supplied override for values the before_insert/before_update
listeners (packages/db/listeners.py) compute unconditionally. `extra="forbid"`
turns an attempt to sneak one in via the request body into a 422, not a
silent no-op.

SubjectCreate takes strategy_slug, not strategy_id: a strategy's slug is
known at code-registration time and needs no DB round trip, which is what
lets /subjects/preview-eligibility stay a pure, no-DB-access endpoint (see
packages/research/dispatch.py). The router resolves slug to the real
strategy_id FK only on the path that persists a Subject; strategy_id is not
on SubjectUpdate at all -- a subject's strategy is immutable after creation,
since risk_flags and attributes are shaped by it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from packages.domain.enums import (
    ArchiveProvider,
    LegalRisk,
    MonetizationTier,
    Platform,
    ResolutionStatus,
    SourceTier,
    SubjectStatus,
)
from packages.research.gate import SourceGateFailureReason


class SubjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_slug: str
    slug: str
    title: str
    event_year: int
    country: str
    region: str | None = None
    summary: str
    resolution_status: ResolutionStatus
    living_persons_involved: bool = False
    risk_flags: list[str] = []
    attributes: dict[str, Any] = {}
    documentation_score: int | None = None
    estimated_runtime_min: int | None = None
    status: SubjectStatus = SubjectStatus.CANDIDATE
    rejected_reason: str | None = None


class SubjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = None
    title: str | None = None
    event_year: int | None = None
    country: str | None = None
    region: str | None = None
    summary: str | None = None
    resolution_status: ResolutionStatus | None = None
    living_persons_involved: bool | None = None
    risk_flags: list[str] | None = None
    attributes: dict[str, Any] | None = None
    documentation_score: int | None = None
    estimated_runtime_min: int | None = None
    status: SubjectStatus | None = None
    rejected_reason: str | None = None


class SubjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    strategy_id: int
    slug: str
    title: str
    event_year: int
    country: str
    region: str | None
    summary: str
    resolution_status: ResolutionStatus
    living_persons_involved: bool
    risk_flags: list[str]
    attributes: dict[str, Any]
    documentation_score: int | None
    estimated_runtime_min: int | None
    monetization_tier: MonetizationTier
    legal_risk: LegalRisk
    eligibility_notes: list[str]
    status: SubjectStatus
    rejected_reason: str | None


class SubjectListResponse(BaseModel):
    items: list[SubjectRead]
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
    tier_a_source_count: int
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
    subject_id: int
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


class StrategyRead(BaseModel):
    """risk_flags and attributes_schema don't come from the Strategy table --

    they're read from that strategy's *code* registration
    (packages/research/dispatch.py) at request time. See docs/SCHEMA.md:
    a strategy's vocabulary is code, not database configuration, and this
    is the one place that vocabulary crosses into the API so a client never
    has to hardcode it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    slug: str
    name: str
    description: str
    subject_noun_singular: str
    subject_noun_plural: str
    min_verified_sources: int
    min_primary_records: int
    min_distinct_domains: int
    style_guide: dict[str, Any]
    allowed_archive_providers: list[ArchiveProvider]
    is_active: bool
    risk_flags: list[str]
    attributes_schema: dict[str, Any]


class ChannelCreate(BaseModel):
    """No credentials field on purpose -- credentials_ref names a macOS
    Keychain entry, it is never the secret itself. There is no endpoint
    anywhere in this API that accepts or returns token/key material; see
    CLAUDE.md's secret-handling rule and docs/SCHEMA.md.
    """

    model_config = ConfigDict(extra="forbid")

    platform: Platform
    display_name: str
    external_account_id: str
    credentials_ref: str
    is_active: bool = True


class ChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    external_account_id: str | None = None
    credentials_ref: str | None = None
    is_active: bool | None = None


class ChannelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    strategy_id: int
    platform: Platform
    display_name: str
    external_account_id: str
    credentials_ref: str
    is_active: bool
