from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from packages.db.models import Channel, Source, Strategy, Subject
from packages.domain.enums import Platform, ResolutionStatus, SourceTier
from packages.strategies.criminal_cases import SLUG as CRIMINAL_CASES_SLUG
from packages.strategies.criminal_cases.enums import CaseType


def make_strategy(**overrides: Any) -> Strategy:
    defaults: dict[str, Any] = dict(
        slug=CRIMINAL_CASES_SLUG,
        name="Criminal Cases",
        description="Well-documented criminal cases with primary-record sourcing.",
        subject_noun_singular="case",
        subject_noun_plural="cases",
        min_verified_sources=3,
        min_primary_records=1,
        min_distinct_domains=3,
        style_guide={},
        allowed_archive_providers=[],
    )
    defaults.update(overrides)
    return Strategy(**defaults)


def make_subject(strategy_id: int, **overrides: Any) -> Subject:
    defaults: dict[str, Any] = dict(
        strategy_id=strategy_id,
        slug="test-subject",
        title="Test Subject",
        attributes={"case_type": CaseType.HOMICIDE},
        event_year=1950,
        country="US",
        region=None,
        summary="A test subject.",
        resolution_status=ResolutionStatus.CONVICTED,
        living_persons_involved=False,
        risk_flags=[],
        documentation_score=4,
    )
    defaults.update(overrides)
    return Subject(**defaults)


def make_channel(strategy_id: int, **overrides: Any) -> Channel:
    defaults: dict[str, Any] = dict(
        strategy_id=strategy_id,
        platform=Platform.YOUTUBE,
        display_name="",
        external_account_id="",
        credentials_ref="",
        is_active=False,
    )
    defaults.update(overrides)
    return Channel(**defaults)


def make_source(subject_id: int, **overrides: Any) -> Source:
    # domain is derived from url by packages/db/listeners.py; not settable here.
    defaults: dict[str, Any] = dict(
        subject_id=subject_id,
        url="https://example.com/article",
        publisher="Example Publisher",
        title="An article",
        published_date=None,
        retrieved_at=datetime.now(UTC),
        tier=SourceTier.RETROSPECTIVE,
        text_path="/tmp/text.txt",
        text_sha256="0" * 64,
        word_count=500,
    )
    defaults.update(overrides)
    return Source(**defaults)
