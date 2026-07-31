"""Eligibility must be enforced at the persistence layer, not by caller discipline.

These tests are adversarial on purpose: they hand-set a wrong monetization_tier
and confirm the before_insert/before_update listeners overwrite it regardless.
"""

from __future__ import annotations

from sqlmodel import Session

from packages.db.models import Case
from packages.domain.enums import MonetizationTier, RiskFlag
from tests.factories import make_case


def test_hand_set_tier_does_not_survive_insert(session: Session) -> None:
    case = make_case(risk_flags=[RiskFlag.CHILD_VICTIM])
    case.monetization_tier = MonetizationTier.GREEN  # deliberately wrong

    session.add(case)
    session.commit()
    case_id = case.id
    assert case_id is not None

    engine = session.get_bind()
    session.close()

    with Session(engine) as fresh_session:
        reloaded = fresh_session.get(Case, case_id)
        assert reloaded is not None
        assert reloaded.monetization_tier == MonetizationTier.RED


def test_hand_set_tier_does_not_survive_update(session: Session) -> None:
    case = make_case(risk_flags=[])
    session.add(case)
    session.commit()
    case_id = case.id
    assert case_id is not None
    assert case.monetization_tier != MonetizationTier.RED

    case.risk_flags = [RiskFlag.CHILD_VICTIM]
    case.monetization_tier = MonetizationTier.GREEN  # deliberately wrong
    session.add(case)
    session.commit()

    engine = session.get_bind()
    session.close()

    with Session(engine) as fresh_session:
        reloaded = fresh_session.get(Case, case_id)
        assert reloaded is not None
        assert reloaded.monetization_tier == MonetizationTier.RED
