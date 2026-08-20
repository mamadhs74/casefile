"""Protocol for the automatic Section (GROUND/RESOLUTION/None) tagging
step -- gemini_section_tagging_provider.py is the one real
implementation, same shape as composition_provider.py /
gemini_composition_provider.py.

Tags per source-story, not per subject: GROUND ("the claim establishing
who/what/scale the others build on") and RESOLUTION only mean anything
relative to one story's own claims, not a subject's claims in
aggregate -- a subject can (and, per docs/HANDOFF.md finding #43,
routinely does) aggregate several unrelated stories, and judging them
together would let a GROUND claim from one story get elaborated
alongside a RESOLUTION claim from an unrelated one. The caller (see
packages/script/section_tagging.py) is responsible for grouping claims
by source before calling this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ClaimForTagging:
    """One claim as tagging input, scoped to a single source. claim_type/
    confidence are plain strings, not enum instances -- same reasoning
    ClaimForComposition already documents: this module stays free of any
    dependency on packages.domain.enums, and the caller (which already
    holds real enum values) is responsible for stringifying them."""

    claim_id: int
    statement: str
    claim_type: str
    confidence: str
    date_anchor: str | None


@dataclass(frozen=True)
class TaggedClaim:
    """section is "GROUND", "RESOLUTION", or None -- a plain string (or
    None), not a packages.domain.enums.Section member; the caller
    converts, same reasoning as everywhere else in this layer."""

    claim_id: int
    section: str | None


class SectionTaggingProviderError(Exception):
    """Base class for provider failures a caller should treat as "this
    source's tagging failed," not a crash."""


class TooManyGroundClaimsError(SectionTaggingProviderError):
    """More than one claim tagged GROUND for one source -- violates the
    hard "at most one per source" rule. Not silently truncated to the
    first one; that would hide a real prompt or model failure rather
    than surface it."""

    def __init__(self, source_id: int, claim_ids: list[int]) -> None:
        self.source_id = source_id
        self.claim_ids = claim_ids
        super().__init__(
            f"source {source_id}: {len(claim_ids)} claims tagged GROUND "
            f"(at most one allowed): {claim_ids}"
        )


class MismatchedClaimIdsError(SectionTaggingProviderError):
    """The provider's response didn't tag exactly the claim_ids it was
    given -- a fabricated id, a missing one, or a duplicate. Same
    defensive posture as this codebase's other model-output re-checks
    (cold-open validation, EntityMatch.matched_entity_id)."""

    def __init__(self, source_id: int, expected: set[int], got: set[int]) -> None:
        self.source_id = source_id
        self.expected = expected
        self.got = got
        super().__init__(
            f"source {source_id}: response claim_ids {sorted(got)} don't match "
            f"input claim_ids {sorted(expected)}"
        )


class SectionTaggingProvider(Protocol):
    async def tag_source_claims(
        self, source_id: int, claims: list[ClaimForTagging]
    ) -> list[TaggedClaim]:
        """claims must all share one source (caller's responsibility --
        this module has no Source/Session dependency). Raises
        SectionTaggingProviderError (or a subclass) on any failure,
        including the defensive re-checks above; never returns a
        result that violates them."""
        ...
