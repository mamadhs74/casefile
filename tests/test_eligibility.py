from __future__ import annotations

from datetime import UTC, datetime

import pytest

from packages.db.models import LegalRisk, MonetizationTier, ResolutionStatus, RiskFlag
from packages.research.eligibility import (
    CaseNotEligibleError,
    ensure_eligible_for_episode,
    score_case,
)
from tests.factories import make_case

CURRENT_YEAR = datetime.now(UTC).year


# ---------------------------------------------------------------------------
# RED tier branches
# ---------------------------------------------------------------------------


def test_child_victim_is_red() -> None:
    case = make_case(risk_flags=[RiskFlag.CHILD_VICTIM])
    result = score_case(case)
    assert result.tier == MonetizationTier.RED
    assert any("CHILD_VICTIM" in note for note in result.notes)


def test_graphic_injury_central_is_red() -> None:
    case = make_case(risk_flags=[RiskFlag.GRAPHIC_INJURY_CENTRAL])
    result = score_case(case)
    assert result.tier == MonetizationTier.RED
    assert any("GRAPHIC_INJURY_CENTRAL" in note for note in result.notes)


def test_hate_motivated_with_recent_event_is_red() -> None:
    case = make_case(
        risk_flags=[RiskFlag.HATE_MOTIVATED, RiskFlag.RECENT_EVENT],
        event_year=CURRENT_YEAR - 1,
    )
    result = score_case(case)
    assert result.tier == MonetizationTier.RED
    assert any("HATE_MOTIVATED" in note for note in result.notes)


def test_hate_motivated_alone_is_not_red() -> None:
    """The RED rule requires the *combination* with RECENT_EVENT."""
    case = make_case(risk_flags=[RiskFlag.HATE_MOTIVATED])
    result = score_case(case)
    assert result.tier != MonetizationTier.RED


# ---------------------------------------------------------------------------
# HIGH legal risk branches
# ---------------------------------------------------------------------------


def test_ongoing_litigation_is_high_legal_risk() -> None:
    case = make_case(risk_flags=[RiskFlag.ONGOING_LITIGATION])
    result = score_case(case)
    assert result.legal_risk == LegalRisk.HIGH
    assert any("ONGOING_LITIGATION" in note for note in result.notes)


def test_named_living_suspect_unconvicted_is_high_legal_risk() -> None:
    case = make_case(
        risk_flags=[RiskFlag.NAMED_LIVING_SUSPECT],
        resolution_status=ResolutionStatus.UNSOLVED,
    )
    result = score_case(case)
    assert result.legal_risk == LegalRisk.HIGH
    assert any("NAMED_LIVING_SUSPECT" in note for note in result.notes)


def test_named_living_suspect_convicted_is_not_high_legal_risk() -> None:
    """A CONVICTED resolution is the carve-out that avoids defamation exposure."""
    case = make_case(
        risk_flags=[RiskFlag.NAMED_LIVING_SUSPECT],
        resolution_status=ResolutionStatus.CONVICTED,
    )
    result = score_case(case)
    assert result.legal_risk != LegalRisk.HIGH


# ---------------------------------------------------------------------------
# Other tiers
# ---------------------------------------------------------------------------


def test_null_documentation_score_is_unknown() -> None:
    case = make_case(documentation_score=None)
    result = score_case(case)
    assert result.tier == MonetizationTier.UNKNOWN


def test_sexual_violence_flag_defaults_yellow() -> None:
    case = make_case(risk_flags=[RiskFlag.SEXUAL_VIOLENCE])
    result = score_case(case)
    assert result.tier == MonetizationTier.YELLOW


def test_thin_documentation_falls_back_to_yellow() -> None:
    case = make_case(risk_flags=[], documentation_score=1)
    result = score_case(case)
    assert result.tier == MonetizationTier.YELLOW


def test_full_green_criteria() -> None:
    case = make_case(
        risk_flags=[],
        documentation_score=5,
        event_year=CURRENT_YEAR - 100,
        living_persons_involved=False,
    )
    result = score_case(case)
    assert result.tier == MonetizationTier.GREEN
    assert result.legal_risk == LegalRisk.LOW
    assert result.notes == []


# ---------------------------------------------------------------------------
# Episode-creation guard
# ---------------------------------------------------------------------------


def test_ensure_eligible_raises_for_red_tier() -> None:
    case = make_case(risk_flags=[RiskFlag.CHILD_VICTIM])
    result = score_case(case)
    assert result.tier == MonetizationTier.RED

    with pytest.raises(CaseNotEligibleError) as exc_info:
        ensure_eligible_for_episode(result)

    assert exc_info.value.result.notes == result.notes
    assert any("CHILD_VICTIM" in note for note in exc_info.value.result.notes)


def test_ensure_eligible_raises_for_high_legal_risk() -> None:
    case = make_case(risk_flags=[RiskFlag.ONGOING_LITIGATION])
    result = score_case(case)
    assert result.legal_risk == LegalRisk.HIGH

    with pytest.raises(CaseNotEligibleError) as exc_info:
        ensure_eligible_for_episode(result)

    assert exc_info.value.result.notes == result.notes
    assert any("ONGOING_LITIGATION" in note for note in exc_info.value.result.notes)


def test_ensure_eligible_passes_for_green() -> None:
    case = make_case(
        risk_flags=[],
        documentation_score=5,
        event_year=CURRENT_YEAR - 100,
        living_persons_involved=False,
    )
    result = score_case(case)
    ensure_eligible_for_episode(result)  # must not raise
