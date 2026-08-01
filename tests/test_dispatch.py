"""The strategy dispatch mechanism itself (packages/research/dispatch.py),
independent of any one strategy's scoring logic.

Confirms the registry does the risk-flag parsing -- not the scorer -- and
that unknown strategies/flags/attributes fail loudly rather than silently
scoring garbage.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from packages.domain.enums import MonetizationTier, ResolutionStatus
from packages.research.dispatch import (
    InvalidSubjectAttributesError,
    UnknownRiskFlagError,
    UnknownStrategyError,
    get_strategy_definition,
    iter_strategy_definitions,
    score_subject,
    validate_attributes,
)
from packages.strategies.criminal_cases import SLUG as CRIMINAL_CASES_SLUG
from packages.strategies.criminal_cases.enums import RiskFlag


@dataclass
class _RawSubject:
    """A plain EligibilityInput-shaped object -- not tied to any ORM/API type,
    to prove the registry works against the protocol, not a concrete class.

    Not frozen: EligibilityInput's Protocol attributes are settable (Subject
    and SubjectCreate both are), and a frozen dataclass's read-only
    attributes don't structurally satisfy that.
    """

    risk_flags: list[str]
    resolution_status: ResolutionStatus = ResolutionStatus.CONVICTED
    event_year: int = 1950
    documentation_score: int | None = 4
    living_persons_involved: bool = False


def test_criminal_cases_is_registered() -> None:
    slugs = {definition.slug for definition in iter_strategy_definitions()}
    assert CRIMINAL_CASES_SLUG in slugs


def test_get_strategy_definition_raises_for_unknown_slug() -> None:
    with pytest.raises(UnknownStrategyError):
        get_strategy_definition("not-a-real-strategy")


def test_score_subject_raises_for_unknown_strategy() -> None:
    with pytest.raises(UnknownStrategyError):
        score_subject(_RawSubject(risk_flags=[]), "not-a-real-strategy")


def test_score_subject_raises_for_unknown_risk_flag() -> None:
    with pytest.raises(UnknownRiskFlagError):
        score_subject(_RawSubject(risk_flags=["not_a_real_flag"]), CRIMINAL_CASES_SLUG)


def test_score_subject_dispatches_to_the_registered_scorer() -> None:
    result = score_subject(
        _RawSubject(risk_flags=[RiskFlag.CHILD_VICTIM.value]), CRIMINAL_CASES_SLUG
    )
    assert result.tier == MonetizationTier.RED
    assert any("CHILD_VICTIM" in note for note in result.notes)


def test_score_subject_never_receives_a_raw_string_flag_it_cannot_parse() -> None:
    """A scorer's parameter type is frozenset[RiskFlag] -- there is no path
    by which score_subject could hand it something unvalidated. This proves
    it from the outside: a bad flag never reaches scoring, it errors first."""
    subject = _RawSubject(risk_flags=["child_victim", "definitely_bogus"])
    with pytest.raises(UnknownRiskFlagError):
        score_subject(subject, CRIMINAL_CASES_SLUG)


def test_validate_attributes_normalizes_valid_attributes() -> None:
    result = validate_attributes(CRIMINAL_CASES_SLUG, {"case_type": "homicide"})
    assert result == {"case_type": "homicide"}


def test_validate_attributes_raises_for_unknown_strategy() -> None:
    with pytest.raises(UnknownStrategyError):
        validate_attributes("not-a-real-strategy", {})


def test_validate_attributes_raises_for_missing_required_key() -> None:
    with pytest.raises(InvalidSubjectAttributesError):
        validate_attributes(CRIMINAL_CASES_SLUG, {})


def test_validate_attributes_raises_for_unrecognized_key() -> None:
    with pytest.raises(InvalidSubjectAttributesError):
        validate_attributes(CRIMINAL_CASES_SLUG, {"case_type": "homicide", "extra": "nope"})


def test_validate_attributes_raises_for_invalid_case_type() -> None:
    with pytest.raises(InvalidSubjectAttributesError):
        validate_attributes(CRIMINAL_CASES_SLUG, {"case_type": "not_a_real_case_type"})


def test_pydantic_validation_error_is_the_documented_cause() -> None:
    with pytest.raises(InvalidSubjectAttributesError) as exc_info:
        validate_attributes(CRIMINAL_CASES_SLUG, {})
    assert isinstance(exc_info.value.__cause__, ValidationError)
