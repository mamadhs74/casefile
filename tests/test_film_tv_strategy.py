"""Conformance and registration checks for the film-tv-news strategy.

Mirrors tests/test_strategy_conformance.py's own enforcement, but proven
directly against film-tv-news's StrategyDefinition rather than via that
file's shared registry-iteration parametrization -- this module imports
packages.strategies.film_tv_news itself, so the check below holds
regardless of whether pytest happens to collect this file before or after
test_strategy_conformance.py builds its own _STRATEGIES tuple at import
time.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

import packages.strategies.film_tv_news  # noqa: F401  registers the strategy for this module
from packages.domain.enums import LegalRisk, MonetizationTier, ResolutionStatus
from packages.research.dispatch import (
    TypedEligibilityInput,
    get_strategy_definition,
    score_subject,
)
from packages.strategies.film_tv_news import SLUG
from packages.strategies.film_tv_news.attributes import Attributes
from packages.strategies.film_tv_news.enums import RiskFlag, TopicType
from tests.test_strategy_conformance import _assert_living_persons_never_low

_DEFINITION = get_strategy_definition(SLUG)


def test_registered_under_its_slug() -> None:
    assert _DEFINITION.slug == SLUG
    assert _DEFINITION.risk_flag_enum is RiskFlag
    assert _DEFINITION.attributes_model is Attributes


def test_living_persons_involved_is_never_low_legal_risk() -> None:
    _assert_living_persons_never_low(_DEFINITION)


def test_attributes_accepts_a_valid_topic_type() -> None:
    attrs = Attributes(topic_type=TopicType.BOX_OFFICE)
    assert attrs.topic_type == TopicType.BOX_OFFICE


def test_attributes_rejects_an_unrecognized_key() -> None:
    with pytest.raises(ValidationError):
        Attributes.model_validate({"topic_type": "box_office", "extra_field": "not allowed"})


@dataclass
class _RawEligibilityInput:
    """A plain stand-in for Subject/SubjectCreate -- satisfies
    packages.domain.protocols.EligibilityInput structurally, same as those
    two do, without needing either's full set of unrelated fields. Not
    frozen: EligibilityInput's attributes are plain (settable) attributes,
    and mypy treats a frozen dataclass's read-only attributes as violating
    that structurally, even though nothing here ever mutates one."""

    risk_flags: list[str]
    resolution_status: ResolutionStatus
    event_year: int
    documentation_score: int | None
    living_persons_involved: bool


def test_score_subject_end_to_end_through_dispatch() -> None:
    """Exercises the real dispatch.score_subject path -- raw string risk
    flags parsed into RiskFlag by dispatch itself, not a hand-built
    TypedEligibilityInput."""
    raw = _RawEligibilityInput(
        risk_flags=[RiskFlag.ONGOING_LITIGATION.value],
        resolution_status=ResolutionStatus.DISPUTED,
        event_year=2026,
        documentation_score=4,
        living_persons_involved=True,
    )
    result = score_subject(raw, SLUG)
    assert result.legal_risk == LegalRisk.HIGH


def test_green_requires_no_risk_flags_and_enough_documentation() -> None:
    subject: TypedEligibilityInput[RiskFlag] = TypedEligibilityInput(
        risk_flags=frozenset(),
        resolution_status=ResolutionStatus.DISPUTED,
        event_year=2026,
        documentation_score=3,
        living_persons_involved=True,
    )
    result = _DEFINITION.scorer(subject)
    assert result.tier == MonetizationTier.GREEN


def test_unverified_allegation_about_a_named_individual_is_red() -> None:
    subject: TypedEligibilityInput[RiskFlag] = TypedEligibilityInput(
        risk_flags=frozenset(
            {RiskFlag.NAMED_LIVING_INDIVIDUAL_ALLEGATION, RiskFlag.UNVERIFIED_RUMOR_CENTRAL}
        ),
        resolution_status=ResolutionStatus.DISPUTED,
        event_year=2026,
        documentation_score=5,
        living_persons_involved=True,
    )
    result = _DEFINITION.scorer(subject)
    assert result.tier == MonetizationTier.RED
    assert result.legal_risk == LegalRisk.HIGH


def test_minor_involved_alone_is_yellow_not_red() -> None:
    subject: TypedEligibilityInput[RiskFlag] = TypedEligibilityInput(
        risk_flags=frozenset({RiskFlag.MINOR_INVOLVED}),
        resolution_status=ResolutionStatus.DISPUTED,
        event_year=2026,
        documentation_score=5,
        living_persons_involved=False,
    )
    result = _DEFINITION.scorer(subject)
    assert result.tier == MonetizationTier.YELLOW


def test_documentation_score_none_is_unknown() -> None:
    subject: TypedEligibilityInput[RiskFlag] = TypedEligibilityInput(
        risk_flags=frozenset(),
        resolution_status=ResolutionStatus.DISPUTED,
        event_year=2026,
        documentation_score=None,
        living_persons_involved=False,
    )
    result = _DEFINITION.scorer(subject)
    assert result.tier == MonetizationTier.UNKNOWN
