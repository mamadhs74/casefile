"""Invariants every registered strategy must hold, checked generically against
the dispatch registry rather than against one strategy's test suite.

Why this exists: today R7 (living/named individuals need extra care) is
enforced because criminal-cases' scorer is the only scorer that exists --
every subject runs through it, so it's structurally impossible to add a
subject that skips the check. Once a second strategy registers its own
scorer, that stops being true by construction; a new strategy's author has
to remember to encode an equivalent protection themselves. This suite is
the guardrail: it runs against every registered strategy automatically, so
a strategy that forgets fails CI instead of failing silently in production.
Start small (living_persons_involved only) and grow this file as more
cross-strategy invariants get identified.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

import packages.strategies.criminal_cases  # noqa: F401  ensures it's registered for collection
from packages.domain.enums import LegalRisk, MonetizationTier, ResolutionStatus
from packages.research.dispatch import (
    StrategyDefinition,
    TypedEligibilityInput,
    iter_strategy_definitions,
)
from packages.research.eligibility import EligibilityResult

_STRATEGIES = iter_strategy_definitions()


def _assert_living_persons_never_low(definition: StrategyDefinition[Any]) -> None:
    """The simplest possible case: living persons involved, nothing else
    complicating it. A strategy that scores this LOW has no protection for
    living, non-public individuals at all -- see R7 in CLAUDE.md."""
    subject: TypedEligibilityInput[Any] = TypedEligibilityInput(
        risk_flags=frozenset(),
        resolution_status=ResolutionStatus.DISPUTED,
        event_year=2020,
        documentation_score=5,
        living_persons_involved=True,
    )

    result = definition.scorer(subject)

    assert result.legal_risk != LegalRisk.LOW, (
        f"strategy {definition.slug!r} scored living_persons_involved=True as LOW legal "
        "risk -- it has no equivalent to criminal-cases' living/recent-event protection"
    )


@pytest.mark.parametrize("definition", _STRATEGIES, ids=[d.slug for d in _STRATEGIES])
def test_living_persons_involved_is_never_low_legal_risk(
    definition: StrategyDefinition[Any],
) -> None:
    _assert_living_persons_never_low(definition)


# ---------------------------------------------------------------------------
# Proof the check above has teeth -- a local-only fixture, never registered
# with packages.research.dispatch, so it can't leak into the real registry
# or into the parametrized test above.
# ---------------------------------------------------------------------------


class _BrokenRiskFlag(StrEnum):
    SOMETHING = "something"


class _BrokenAttributes(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _always_low_scorer(subject: TypedEligibilityInput[_BrokenRiskFlag]) -> EligibilityResult:
    """The violation this suite exists to catch: ignores living_persons_involved
    entirely and always reports LOW legal risk."""
    return EligibilityResult(tier=MonetizationTier.GREEN, legal_risk=LegalRisk.LOW, notes=[])


_BROKEN_DEFINITION: StrategyDefinition[_BrokenRiskFlag] = StrategyDefinition(
    slug="test-broken-strategy",
    risk_flag_enum=_BrokenRiskFlag,
    scorer=_always_low_scorer,
    attributes_model=_BrokenAttributes,
)


def test_conformance_check_fails_against_a_strategy_that_ignores_living_persons() -> None:
    """If this test ever fails, the invariant above has stopped meaning
    anything -- it would pass a scorer that provides no protection at all."""
    with pytest.raises(AssertionError):
        _assert_living_persons_never_low(_BROKEN_DEFINITION)


def test_broken_fixture_was_never_added_to_the_real_registry() -> None:
    real_slugs = {definition.slug for definition in iter_strategy_definitions()}
    assert _BROKEN_DEFINITION.slug not in real_slugs
