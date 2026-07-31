"""Eligibility scoring per docs/SCHEMA.md.

Pure function, no DB access, fully unit-testable. Recomputed on every write to
`Case` by the caller (the API layer owns persistence).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from packages.db.models import Case, LegalRisk, MonetizationTier, ResolutionStatus, RiskFlag

GREEN_MIN_DOCUMENTATION_SCORE = 3
GREEN_MIN_YEARS_SINCE_EVENT = 25

_YELLOW_FLAGS = frozenset(
    {
        RiskFlag.SEXUAL_VIOLENCE,
        RiskFlag.SUICIDE_CENTRAL,
        RiskFlag.POLITICAL_VIOLENCE,
        RiskFlag.RECENT_EVENT,
    }
)


@dataclass(frozen=True)
class EligibilityResult:
    tier: MonetizationTier
    legal_risk: LegalRisk
    notes: list[str] = field(default_factory=list)


class CaseNotEligibleError(Exception):
    """Raised when the API attempts to create an Episode for a blocked case."""

    def __init__(self, result: EligibilityResult) -> None:
        self.result = result
        super().__init__(
            f"case not eligible for production (tier={result.tier}, "
            f"legal_risk={result.legal_risk}): {'; '.join(result.notes)}"
        )


def score_case(case: Case) -> EligibilityResult:
    flags = set(case.risk_flags)
    tier, tier_notes = _score_tier(case, flags)
    legal_risk, risk_notes = _score_legal_risk(case, flags)
    return EligibilityResult(tier=tier, legal_risk=legal_risk, notes=[*tier_notes, *risk_notes])


def _score_tier(case: Case, flags: set[RiskFlag]) -> tuple[MonetizationTier, list[str]]:
    if RiskFlag.CHILD_VICTIM in flags:
        return (
            MonetizationTier.RED,
            ["CHILD_VICTIM present: not eligible for ad revenue, no framing rescues this"],
        )
    if RiskFlag.GRAPHIC_INJURY_CENTRAL in flags:
        return (
            MonetizationTier.RED,
            [
                "GRAPHIC_INJURY_CENTRAL present: injury is the story, "
                "no documentary framing fixes this"
            ],
        )
    if RiskFlag.HATE_MOTIVATED in flags and RiskFlag.RECENT_EVENT in flags:
        return (
            MonetizationTier.RED,
            ["HATE_MOTIVATED combined with RECENT_EVENT"],
        )

    if case.documentation_score is None:
        return (
            MonetizationTier.UNKNOWN,
            ["documentation_score is null: cannot score without knowing record depth"],
        )

    yellow_flags = flags & _YELLOW_FLAGS
    if yellow_flags:
        notes = [
            f"{flag.value} present: default yellow, may promote to green after script-level "
            "style pass"
            for flag in sorted(yellow_flags, key=lambda f: f.value)
        ]
        return MonetizationTier.YELLOW, notes

    current_year = datetime.now(UTC).year
    recent = case.event_year > current_year - GREEN_MIN_YEARS_SINCE_EVENT
    thin_docs = case.documentation_score < GREEN_MIN_DOCUMENTATION_SCORE
    living = case.living_persons_involved

    if not recent and not thin_docs and not living:
        return MonetizationTier.GREEN, []

    notes = []
    if recent:
        notes.append(
            f"event_year {case.event_year} is within the last "
            f"{GREEN_MIN_YEARS_SINCE_EVENT} years"
        )
    if thin_docs:
        notes.append(
            f"documentation_score {case.documentation_score} is below the green threshold "
            f"of {GREEN_MIN_DOCUMENTATION_SCORE}"
        )
    if living:
        notes.append("living_persons_involved is true")
    return MonetizationTier.YELLOW, notes


def _score_legal_risk(case: Case, flags: set[RiskFlag]) -> tuple[LegalRisk, list[str]]:
    if RiskFlag.ONGOING_LITIGATION in flags:
        return (
            LegalRisk.HIGH,
            ["ONGOING_LITIGATION present: high legal risk, do not produce"],
        )

    named_living_suspect_unconvicted = (
        RiskFlag.NAMED_LIVING_SUSPECT in flags
        and case.resolution_status != ResolutionStatus.CONVICTED
    )
    if named_living_suspect_unconvicted:
        return (
            LegalRisk.HIGH,
            [
                "NAMED_LIVING_SUSPECT present with resolution_status="
                f"{case.resolution_status.value}: defamation exposure, do not produce"
            ],
        )

    if (
        RiskFlag.NAMED_LIVING_SUSPECT in flags
        or case.living_persons_involved
        or RiskFlag.RECENT_EVENT in flags
    ):
        return (
            LegalRisk.MEDIUM,
            ["living or recent-event exposure: elevated but non-blocking legal risk"],
        )

    return LegalRisk.LOW, []


def ensure_eligible_for_episode(result: EligibilityResult) -> None:
    """Guard used before creating an Episode. Raises CaseNotEligibleError if blocked."""
    if result.tier == MonetizationTier.RED or result.legal_risk == LegalRisk.HIGH:
        raise CaseNotEligibleError(result)
