from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from packages.db.models import Case, Source
from packages.domain.enums import CaseType, ResolutionStatus, SourceTier


def make_case(**overrides: Any) -> Case:
    defaults: dict[str, Any] = dict(
        slug="test-case",
        title="Test Case",
        case_type=CaseType.HOMICIDE,
        event_year=1950,
        country="US",
        region=None,
        summary="A test case.",
        resolution_status=ResolutionStatus.CONVICTED,
        living_persons_involved=False,
        risk_flags=[],
        documentation_score=4,
    )
    defaults.update(overrides)
    return Case(**defaults)


def make_source(case_id: int, **overrides: Any) -> Source:
    # domain is derived from url by packages/db/listeners.py; not settable here.
    defaults: dict[str, Any] = dict(
        case_id=case_id,
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
