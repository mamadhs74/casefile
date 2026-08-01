"""Strategy dispatch for eligibility scoring and subject attribute validation.

A Strategy's risk-flag vocabulary, eligibility logic, and attribute shape are
strategy-owned code (packages/strategies/<slug>/), not database
configuration -- see docs/SCHEMA.md. This module is the one place that
resolves a strategy slug to that code, and it does the risk-flag parsing
itself before a scorer ever runs. A scorer's signature only accepts
`frozenset[<its own enum>]` -- there is no code path by which caller
discipline could hand it a raw, unvalidated string instead.

Each strategy package registers itself as an import side effect (mirroring
packages/db/listeners.py's own registration pattern) -- something must
import packages.strategies.<slug> before score_subject/validate_attributes
can find it. packages/db/listeners.py does this for every known strategy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from packages.domain.enums import ResolutionStatus
from packages.domain.protocols import EligibilityInput
from packages.research.eligibility import EligibilityResult


class UnknownStrategyError(Exception):
    def __init__(self, strategy_slug: object) -> None:
        self.strategy_slug = strategy_slug
        super().__init__(f"unknown strategy: {strategy_slug!r}")


class UnknownRiskFlagError(Exception):
    def __init__(self, strategy_slug: str, flag: str) -> None:
        self.strategy_slug = strategy_slug
        self.flag = flag
        super().__init__(f"strategy {strategy_slug!r} has no risk flag {flag!r}")


class InvalidSubjectAttributesError(Exception):
    def __init__(self, strategy_slug: str, detail: str) -> None:
        self.strategy_slug = strategy_slug
        self.detail = detail
        super().__init__(f"invalid attributes for strategy {strategy_slug!r}: {detail}")


@dataclass(frozen=True)
class TypedEligibilityInput[E: StrEnum]:
    """What a strategy's scorer actually receives.

    risk_flags is already parsed into that strategy's own enum by
    score_subject below -- a scorer never sees a raw string.
    """

    risk_flags: frozenset[E]
    resolution_status: ResolutionStatus
    event_year: int
    documentation_score: int | None
    living_persons_involved: bool


class Scorer[E: StrEnum](Protocol):
    def __call__(self, subject: TypedEligibilityInput[E]) -> EligibilityResult: ...


@dataclass(frozen=True)
class StrategyDefinition[E: StrEnum]:
    slug: str
    risk_flag_enum: type[E]
    scorer: Scorer[E]
    attributes_model: type[BaseModel]


_REGISTRY: dict[str, StrategyDefinition[Any]] = {}


def register_strategy(definition: StrategyDefinition[Any]) -> None:
    _REGISTRY[definition.slug] = definition


def get_strategy_definition(strategy_slug: str) -> StrategyDefinition[Any]:
    definition = _REGISTRY.get(strategy_slug)
    if definition is None:
        raise UnknownStrategyError(strategy_slug)
    return definition


def iter_strategy_definitions() -> tuple[StrategyDefinition[Any], ...]:
    """Every registered strategy. The cross-strategy conformance suite iterates this."""
    return tuple(_REGISTRY.values())


def _parse_risk_flags[E: StrEnum](
    raw: list[str], strategy_slug: str, enum_cls: type[E]
) -> frozenset[E]:
    parsed: set[E] = set()
    for value in raw:
        try:
            parsed.add(enum_cls(value))
        except ValueError as exc:
            raise UnknownRiskFlagError(strategy_slug, value) from exc
    return frozenset(parsed)


def score_subject(raw: EligibilityInput, strategy_slug: str) -> EligibilityResult:
    """Pure -- touches no DB, same guarantee the old score_case() made.

    Resolves risk flags into the strategy's own enum before the scorer ever
    sees them, so an unrecognized or wrong-strategy flag is rejected here,
    not silently scored.
    """
    definition = get_strategy_definition(strategy_slug)
    typed_flags = _parse_risk_flags(list(raw.risk_flags), strategy_slug, definition.risk_flag_enum)
    typed_input = TypedEligibilityInput(
        risk_flags=typed_flags,
        resolution_status=raw.resolution_status,
        event_year=raw.event_year,
        documentation_score=raw.documentation_score,
        living_persons_involved=raw.living_persons_involved,
    )
    return definition.scorer(typed_input)


def validate_attributes(strategy_slug: str, attributes: dict[str, Any]) -> dict[str, Any]:
    """Validates + normalizes a subject's attributes JSON against its strategy's shape."""
    definition = get_strategy_definition(strategy_slug)
    try:
        validated = definition.attributes_model(**attributes)
    except ValidationError as exc:
        raise InvalidSubjectAttributesError(strategy_slug, str(exc)) from exc
    return validated.model_dump(mode="json")
