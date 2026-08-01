"""Eligibility and attribute validation must be enforced at the persistence
layer, not by caller discipline.

These tests are adversarial on purpose: they hand-set a wrong
monetization_tier or invalid attributes and confirm the before_insert/
before_update listener overwrites or rejects them regardless.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from packages.db.models import Strategy, Subject
from packages.domain.enums import MonetizationTier
from packages.research.dispatch import InvalidSubjectAttributesError, UnknownStrategyError
from packages.strategies.criminal_cases.enums import CaseType, RiskFlag
from tests.factories import make_strategy, make_subject


def test_hand_set_tier_does_not_survive_insert(session: Session, strategy_id: int) -> None:
    subject = make_subject(strategy_id, risk_flags=[RiskFlag.CHILD_VICTIM])
    subject.monetization_tier = MonetizationTier.GREEN  # deliberately wrong

    session.add(subject)
    session.commit()
    subject_id = subject.id
    assert subject_id is not None

    engine = session.get_bind()
    session.close()

    with Session(engine) as fresh_session:
        reloaded = fresh_session.get(Subject, subject_id)
        assert reloaded is not None
        assert reloaded.monetization_tier == MonetizationTier.RED


def test_hand_set_tier_does_not_survive_update(session: Session, strategy_id: int) -> None:
    subject = make_subject(strategy_id, risk_flags=[])
    session.add(subject)
    session.commit()
    subject_id = subject.id
    assert subject_id is not None
    assert subject.monetization_tier != MonetizationTier.RED

    subject.risk_flags = [RiskFlag.CHILD_VICTIM]
    subject.monetization_tier = MonetizationTier.GREEN  # deliberately wrong
    session.add(subject)
    session.commit()

    engine = session.get_bind()
    session.close()

    with Session(engine) as fresh_session:
        reloaded = fresh_session.get(Subject, subject_id)
        assert reloaded is not None
        assert reloaded.monetization_tier == MonetizationTier.RED


def test_hand_set_attributes_are_normalized_not_trusted(
    session: Session, strategy_id: int
) -> None:
    """Passing the enum member directly (not its .value string) must still
    end up stored as the normalized JSON string -- proof attributes go
    through validate_attributes() rather than being stored as handed in."""
    subject = make_subject(strategy_id, attributes={"case_type": CaseType.MARITIME})

    session.add(subject)
    session.commit()
    subject_id = subject.id
    assert subject_id is not None

    engine = session.get_bind()
    session.close()

    with Session(engine) as fresh_session:
        reloaded = fresh_session.get(Subject, subject_id)
        assert reloaded is not None
        assert reloaded.attributes == {"case_type": "maritime"}


def test_invalid_attributes_are_rejected_even_bypassing_the_api(
    session: Session, strategy_id: int
) -> None:
    subject = make_subject(strategy_id, attributes={"case_type": "not_a_real_case_type"})

    session.add(subject)
    with pytest.raises(InvalidSubjectAttributesError):
        session.commit()


def test_strategy_row_with_no_registered_code_raises_on_subject_write(session: Session) -> None:
    """A Strategy row can exist in the database with no matching entry in
    packages.research.dispatch's registry -- e.g. seeded before its
    packages/strategies/ package was written, or a typo'd slug. Two-step
    registration (see docs/SCHEMA.md) means this must fail loudly, not
    silently skip attribute validation and eligibility scoring."""
    ghost_strategy: Strategy = make_strategy(slug="ghost-strategy-no-code-package")
    session.add(ghost_strategy)
    session.commit()
    session.refresh(ghost_strategy)
    assert ghost_strategy.id is not None

    subject = make_subject(ghost_strategy.id)
    session.add(subject)
    with pytest.raises(UnknownStrategyError):
        session.commit()
