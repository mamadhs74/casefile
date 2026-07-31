from __future__ import annotations

from sqlmodel import Session

from packages.db.models import Case
from packages.domain.enums import SourceTier
from packages.research.gate import SourceGateFailureReason, check_source_gate
from tests.factories import make_case, make_source


def _persist_case(session: Session, case: Case) -> int:
    session.add(case)
    session.commit()
    session.refresh(case)
    assert case.id is not None
    return case.id


def test_gate_fails_on_insufficient_verified_sources(session: Session) -> None:
    case_id = _persist_case(session, make_case())
    session.add(make_source(case_id, url="https://a.com/1", tier=SourceTier.PRIMARY_RECORD))
    session.add(make_source(case_id, url="https://b.com/1", tier=SourceTier.UNVERIFIED))
    session.add(make_source(case_id, url="https://c.com/1", tier=SourceTier.UNVERIFIED))
    session.commit()

    result = check_source_gate(case_id, session=session)

    assert result.passed is False
    assert SourceGateFailureReason.INSUFFICIENT_VERIFIED_SOURCES in result.reasons
    assert result.verified_source_count == 1


def test_gate_fails_on_missing_primary_record(session: Session) -> None:
    case_id = _persist_case(session, make_case())
    session.add(make_source(case_id, url="https://a.com/1", tier=SourceTier.RETROSPECTIVE))
    session.add(make_source(case_id, url="https://b.com/1", tier=SourceTier.CONTEMPORANEOUS))
    session.add(make_source(case_id, url="https://c.com/1", tier=SourceTier.BOOK))
    session.commit()

    result = check_source_gate(case_id, session=session)

    assert result.passed is False
    assert SourceGateFailureReason.MISSING_PRIMARY_RECORD in result.reasons
    assert result.primary_record_count == 0


def test_gate_fails_on_insufficient_distinct_domains(session: Session) -> None:
    case_id = _persist_case(session, make_case())
    session.add(make_source(case_id, url="https://a.com/1", tier=SourceTier.PRIMARY_RECORD))
    session.add(make_source(case_id, url="https://a.com/2", tier=SourceTier.RETROSPECTIVE))
    session.add(make_source(case_id, url="https://b.com/1", tier=SourceTier.CONTEMPORANEOUS))
    session.commit()

    result = check_source_gate(case_id, session=session)

    assert result.passed is False
    assert SourceGateFailureReason.INSUFFICIENT_DISTINCT_DOMAINS in result.reasons
    assert result.distinct_domain_count == 2


def test_gate_passes_when_all_three_conditions_hold(session: Session) -> None:
    case_id = _persist_case(session, make_case())
    session.add(make_source(case_id, url="https://a.com/1", tier=SourceTier.PRIMARY_RECORD))
    session.add(make_source(case_id, url="https://b.com/1", tier=SourceTier.CONTEMPORANEOUS))
    session.add(make_source(case_id, url="https://c.com/1", tier=SourceTier.RETROSPECTIVE))
    session.add(make_source(case_id, url="https://d.com/1", tier=SourceTier.UNVERIFIED))
    session.commit()

    result = check_source_gate(case_id, session=session)

    assert result.passed is True
    assert result.reasons == []
    assert result.verified_source_count == 3
    assert result.primary_record_count == 1
    assert result.distinct_domain_count == 3


def test_bbc_subdomains_collapse_to_one_domain_and_fail_distinct_domain_gate(
    session: Session,
) -> None:
    """www., bare, and amp. are all the same registrable domain -- not independent sources."""
    case_id = _persist_case(session, make_case())
    session.add(
        make_source(case_id, url="https://www.bbc.co.uk/news/1", tier=SourceTier.PRIMARY_RECORD)
    )
    session.add(
        make_source(case_id, url="https://bbc.co.uk/news/2", tier=SourceTier.CONTEMPORANEOUS)
    )
    session.add(
        make_source(case_id, url="https://amp.bbc.co.uk/news/3", tier=SourceTier.RETROSPECTIVE)
    )
    session.commit()

    result = check_source_gate(case_id, session=session)

    assert result.passed is False
    assert SourceGateFailureReason.INSUFFICIENT_DISTINCT_DOMAINS in result.reasons
    assert result.distinct_domain_count == 1
    assert result.verified_source_count == 3
    assert result.primary_record_count == 1
