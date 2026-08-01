"""The strategy-agnostic core of eligibility: the shared output vocabulary and
the episode-creation guard.

Actual scoring logic (score_case and friends) lives per-strategy under
packages/strategies/<slug>/eligibility.py and is reached through
packages/research/dispatch.py::score_subject. This module holds only what
every strategy must produce and what every episode-creation path must check
-- both are strategy-agnostic by design. See docs/SCHEMA.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.domain.enums import LegalRisk, MonetizationTier


@dataclass(frozen=True)
class EligibilityResult:
    tier: MonetizationTier
    legal_risk: LegalRisk
    notes: list[str] = field(default_factory=list)


class SubjectNotEligibleError(Exception):
    """Raised when the API attempts to create an Episode for a blocked subject."""

    def __init__(self, result: EligibilityResult) -> None:
        self.result = result
        super().__init__(
            f"subject not eligible for production (tier={result.tier}, "
            f"legal_risk={result.legal_risk}): {'; '.join(result.notes)}"
        )


def ensure_eligible_for_episode(result: EligibilityResult) -> None:
    """Guard used before creating an Episode. Raises SubjectNotEligibleError if blocked.

    Strategy-agnostic on purpose: it only ever looks at the universal
    tier/legal_risk output, never at how a strategy arrived at them.
    """
    if result.tier == MonetizationTier.RED or result.legal_risk == LegalRisk.HIGH:
        raise SubjectNotEligibleError(result)
