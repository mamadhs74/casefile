"""criminal-cases' own eligibility scoring. Relocated from tests/test_eligibility.py
-- same assertions, calling packages.strategies.criminal_cases.eligibility.score_case
directly with an already-typed TypedEligibilityInput, since that's what the
dispatch registry actually hands a scorer (packages/research/dispatch.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from packages.domain.enums import LegalRisk, MonetizationTier, ResolutionStatus
from packages.research.dispatch import TypedEligibilityInput
from packages.research.eligibility import SubjectNotEligibleError, ensure_eligible_for_episode
from packages.strategies.criminal_cases.eligibility import score_case
from packages.strategies.criminal_cases.enums import RiskFlag

CURRENT_YEAR = datetime.now(UTC).year


def _input(**overrides: Any) -> TypedEligibilityInput[RiskFlag]:
    defaults: dict[str, Any] = dict(
        risk_flags=frozenset(),
        resolution_status=ResolutionStatus.CONVICTED,
        event_year=1950,
        documentation_score=4,
        living_persons_involved=False,
    )
    defaults.update(overrides)
    return TypedEligibilityInput(**defaults)


# ---------------------------------------------------------------------------
# RED tier branches
# ---------------------------------------------------------------------------


def test_child_victim_is_red() -> None:
    result = score_case(_input(risk_flags=frozenset({RiskFlag.CHILD_VICTIM})))
    assert result.tier == MonetizationTier.RED
    assert any("CHILD_VICTIM" in note for note in result.notes)


def test_graphic_injury_central_is_red() -> None:
    result = score_case(_input(risk_flags=frozenset({RiskFlag.GRAPHIC_INJURY_CENTRAL})))
    assert result.tier == MonetizationTier.RED
    assert any("GRAPHIC_INJURY_CENTRAL" in note for note in result.notes)


def test_hate_motivated_with_recent_event_is_red() -> None:
    result = score_case(
        _input(
            risk_flags=frozenset({RiskFlag.HATE_MOTIVATED, RiskFlag.RECENT_EVENT}),
            event_year=CURRENT_YEAR - 1,
        )
    )
    assert result.tier == MonetizationTier.RED
    assert any("HATE_MOTIVATED" in note for note in result.notes)


def test_hate_motivated_alone_is_not_red() -> None:
    """The RED rule requires the *combination* with RECENT_EVENT."""
    result = score_case(_input(risk_flags=frozenset({RiskFlag.HATE_MOTIVATED})))
    assert result.tier != MonetizationTier.RED


# ---------------------------------------------------------------------------
# HIGH legal risk branches
# ---------------------------------------------------------------------------


def test_ongoing_litigation_is_high_legal_risk() -> None:
    result = score_case(_input(risk_flags=frozenset({RiskFlag.ONGOING_LITIGATION})))
    assert result.legal_risk == LegalRisk.HIGH
    assert any("ONGOING_LITIGATION" in note for note in result.notes)


def test_named_living_suspect_unconvicted_is_high_legal_risk() -> None:
    result = score_case(
        _input(
            risk_flags=frozenset({RiskFlag.NAMED_LIVING_SUSPECT}),
            resolution_status=ResolutionStatus.UNSOLVED,
        )
    )
    assert result.legal_risk == LegalRisk.HIGH
    assert any("NAMED_LIVING_SUSPECT" in note for note in result.notes)


def test_named_living_suspect_convicted_is_not_high_legal_risk() -> None:
    """A CONVICTED resolution is the carve-out that avoids defamation exposure."""
    result = score_case(
        _input(
            risk_flags=frozenset({RiskFlag.NAMED_LIVING_SUSPECT}),
            resolution_status=ResolutionStatus.CONVICTED,
        )
    )
    assert result.legal_risk != LegalRisk.HIGH


# ---------------------------------------------------------------------------
# Other tiers
# ---------------------------------------------------------------------------


def test_null_documentation_score_is_unknown() -> None:
    result = score_case(_input(documentation_score=None))
    assert result.tier == MonetizationTier.UNKNOWN


def test_sexual_violence_flag_defaults_yellow() -> None:
    result = score_case(_input(risk_flags=frozenset({RiskFlag.SEXUAL_VIOLENCE})))
    assert result.tier == MonetizationTier.YELLOW


def test_thin_documentation_falls_back_to_yellow() -> None:
    result = score_case(_input(documentation_score=1))
    assert result.tier == MonetizationTier.YELLOW


def test_full_green_criteria() -> None:
    result = score_case(
        _input(
            documentation_score=5,
            event_year=CURRENT_YEAR - 100,
            living_persons_involved=False,
        )
    )
    assert result.tier == MonetizationTier.GREEN
    assert result.legal_risk == LegalRisk.LOW
    assert result.notes == []


# ---------------------------------------------------------------------------
# Episode-creation guard (strategy-agnostic -- packages/research/eligibility.py)
# ---------------------------------------------------------------------------


def test_ensure_eligible_raises_for_red_tier() -> None:
    result = score_case(_input(risk_flags=frozenset({RiskFlag.CHILD_VICTIM})))
    assert result.tier == MonetizationTier.RED

    with pytest.raises(SubjectNotEligibleError) as exc_info:
        ensure_eligible_for_episode(result)

    assert exc_info.value.result.notes == result.notes
    assert any("CHILD_VICTIM" in note for note in exc_info.value.result.notes)


def test_ensure_eligible_raises_for_high_legal_risk() -> None:
    result = score_case(_input(risk_flags=frozenset({RiskFlag.ONGOING_LITIGATION})))
    assert result.legal_risk == LegalRisk.HIGH

    with pytest.raises(SubjectNotEligibleError) as exc_info:
        ensure_eligible_for_episode(result)

    assert exc_info.value.result.notes == result.notes
    assert any("ONGOING_LITIGATION" in note for note in exc_info.value.result.notes)


def test_ensure_eligible_passes_for_green() -> None:
    result = score_case(
        _input(
            documentation_score=5,
            event_year=CURRENT_YEAR - 100,
            living_persons_involved=False,
        )
    )
    ensure_eligible_for_episode(result)  # must not raise
