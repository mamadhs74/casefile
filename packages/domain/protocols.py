"""Structural contracts shared across layers.

These let packages/research work against a shape rather than a concrete ORM
or API type, so it never needs to import from packages/db or apps/api.
"""

from __future__ import annotations

from typing import Protocol

from packages.domain.enums import ResolutionStatus, RiskFlag


class EligibilityInput(Protocol):
    """The fields score_case() actually reads. Case and CaseCreate both satisfy this."""

    risk_flags: list[RiskFlag]
    resolution_status: ResolutionStatus
    event_year: int
    documentation_score: int | None
    living_persons_involved: bool
