"""Structural contracts shared across layers.

These let packages/research work against a shape rather than a concrete ORM
or API type, so it never needs to import from packages/db or apps/api.
"""

from __future__ import annotations

from typing import Protocol

from packages.domain.enums import ResolutionStatus


class EligibilityInput(Protocol):
    """The fields eligibility scoring reads. Subject and SubjectCreate both satisfy this.

    risk_flags is `list[str]`, not a closed enum -- which strings are valid
    depends on which strategy owns this subject, and that isn't known here.
    packages/research/dispatch.py resolves a strategy's own risk-flag enum
    and validates against it before a scorer ever runs; nothing downstream
    of that point sees an unvalidated string. See docs/SCHEMA.md.
    """

    risk_flags: list[str]
    resolution_status: ResolutionStatus
    event_year: int
    documentation_score: int | None
    living_persons_involved: bool
