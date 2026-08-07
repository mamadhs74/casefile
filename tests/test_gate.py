from __future__ import annotations

from sqlmodel import Session

from packages.db.models import Subject
from packages.domain.enums import SourceTier
from packages.research.gate import SourceGateFailureReason, check_source_gate
from tests.factories import make_source, make_strategy, make_subject


def _persist_subject(session: Session, subject: Subject) -> int:
    session.add(subject)
    session.commit()
    session.refresh(subject)
    assert subject.id is not None
    return subject.id


def test_gate_fails_on_insufficient_verified_sources(session: Session, strategy_id: int) -> None:
    subject_id = _persist_subject(session, make_subject(strategy_id))
    session.add(make_source(subject_id, url="https://a.com/1", tier=SourceTier.PRIMARY_RECORD))
    session.add(make_source(subject_id, url="https://b.com/1", tier=SourceTier.UNVERIFIED))
    session.add(make_source(subject_id, url="https://c.com/1", tier=SourceTier.UNVERIFIED))
    session.commit()

    result = check_source_gate(subject_id, session=session)

    assert result.passed is False
    assert SourceGateFailureReason.INSUFFICIENT_VERIFIED_SOURCES in result.reasons
    assert result.verified_source_count == 1


def test_gate_fails_with_no_tier_a_source(session: Session, strategy_id: int) -> None:
    """RETROSPECTIVE, BOOK, and REFERENCE are all Tier B -- none of PRIMARY_RECORD
    or CONTEMPORANEOUS, so the gate must still fail this condition. Previously
    built with a CONTEMPORANEOUS source in the mix, back when only PRIMARY_RECORD
    counted -- CLAUDE.md's own R1 names "contemporaneous news archive" as a
    primary/public record, and six other enforcement points already treated
    PRIMARY_RECORD and CONTEMPORANEOUS as equally Tier A (TIER_A_SOURCE_TIERS),
    so this gate was the one place they diverged, with no documented reason for
    it. Rewritten to test the condition correctly scoped, not deleted -- see
    docs/SCHEMA.md."""
    subject_id = _persist_subject(session, make_subject(strategy_id))
    session.add(make_source(subject_id, url="https://a.com/1", tier=SourceTier.RETROSPECTIVE))
    session.add(make_source(subject_id, url="https://b.com/1", tier=SourceTier.BOOK))
    session.add(make_source(subject_id, url="https://c.com/1", tier=SourceTier.REFERENCE))
    session.commit()

    result = check_source_gate(subject_id, session=session)

    assert result.passed is False
    assert SourceGateFailureReason.MISSING_TIER_A_SOURCE in result.reasons
    assert result.tier_a_source_count == 0


def test_gate_fails_on_insufficient_distinct_domains(session: Session, strategy_id: int) -> None:
    subject_id = _persist_subject(session, make_subject(strategy_id))
    session.add(make_source(subject_id, url="https://a.com/1", tier=SourceTier.PRIMARY_RECORD))
    session.add(make_source(subject_id, url="https://a.com/2", tier=SourceTier.RETROSPECTIVE))
    session.add(make_source(subject_id, url="https://b.com/1", tier=SourceTier.CONTEMPORANEOUS))
    session.commit()

    result = check_source_gate(subject_id, session=session)

    assert result.passed is False
    assert SourceGateFailureReason.INSUFFICIENT_DISTINCT_DOMAINS in result.reasons
    assert result.distinct_domain_count == 2


def test_gate_passes_when_all_three_conditions_hold(session: Session, strategy_id: int) -> None:
    subject_id = _persist_subject(session, make_subject(strategy_id))
    session.add(make_source(subject_id, url="https://a.com/1", tier=SourceTier.PRIMARY_RECORD))
    session.add(make_source(subject_id, url="https://b.com/1", tier=SourceTier.CONTEMPORANEOUS))
    session.add(make_source(subject_id, url="https://c.com/1", tier=SourceTier.RETROSPECTIVE))
    session.add(make_source(subject_id, url="https://d.com/1", tier=SourceTier.UNVERIFIED))
    session.commit()

    result = check_source_gate(subject_id, session=session)

    assert result.passed is True
    assert result.reasons == []
    assert result.verified_source_count == 3
    assert result.tier_a_source_count == 2  # PRIMARY_RECORD and CONTEMPORANEOUS both count
    assert result.distinct_domain_count == 3


def test_bbc_subdomains_collapse_to_one_domain_and_fail_distinct_domain_gate(
    session: Session, strategy_id: int
) -> None:
    """www., bare, and amp. are all the same registrable domain -- not independent sources."""
    subject_id = _persist_subject(session, make_subject(strategy_id))
    session.add(
        make_source(
            subject_id, url="https://www.bbc.co.uk/news/1", tier=SourceTier.PRIMARY_RECORD
        )
    )
    session.add(
        make_source(subject_id, url="https://bbc.co.uk/news/2", tier=SourceTier.CONTEMPORANEOUS)
    )
    session.add(
        make_source(subject_id, url="https://amp.bbc.co.uk/news/3", tier=SourceTier.RETROSPECTIVE)
    )
    session.commit()

    result = check_source_gate(subject_id, session=session)

    assert result.passed is False
    assert SourceGateFailureReason.INSUFFICIENT_DISTINCT_DOMAINS in result.reasons
    assert result.distinct_domain_count == 1
    assert result.verified_source_count == 3
    assert result.tier_a_source_count == 2  # PRIMARY_RECORD and CONTEMPORANEOUS both count


def test_gate_thresholds_come_from_the_subjects_strategy(session: Session) -> None:
    """A strategy with looser thresholds passes with fewer sources than
    criminal-cases' defaults would allow -- proof the gate reads the row,
    not a module constant."""
    loose_strategy = make_strategy(
        min_verified_sources=1,
        min_primary_records=0,
        min_distinct_domains=1,
    )
    session.add(loose_strategy)
    session.commit()
    session.refresh(loose_strategy)
    assert loose_strategy.id is not None

    subject_id = _persist_subject(session, make_subject(loose_strategy.id))
    session.add(make_source(subject_id, url="https://a.com/1", tier=SourceTier.RETROSPECTIVE))
    session.commit()

    result = check_source_gate(subject_id, session=session)

    assert result.passed is True
