"""Provider interface for entity extraction.

One protocol, no implementation yet (packages/research/gemini_entity_provider.py
is the next step) -- same reasoning as packages/research/llm_provider.py:
nothing in packages/research/entity_extraction.py should import a provider
SDK directly, so swapping providers later means adding a class here that
satisfies EntityExtractionProvider, not touching extraction logic.

Deliberately minimal, same posture as llm_provider.py: one method, one
input shape, one output shape. Not built out with retry/rate-limit/
cost-tracking hooks up front -- add those if and when a second
implementation actually needs them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class KnownEntity:
    """One row of the subject's existing entity list, passed in-prompt so
    the model can decide match-or-new for each mention it finds -- see
    docs/SCHEMA.md's "Entity extraction" section.

    identifying_span/source_id/source_title all come from that entity's
    *founding* EntityMatch, not its most recent one: fixed the moment the
    entity is created, so it doesn't drift depending on what order later
    sources get processed in, and it's the span that was already
    inspected when the entity was judged to be a real, distinct person --
    the most scrutiny already behind it, not an arbitrary pick.

    source_id/source_title exist because name and role alone can't
    disambiguate two real people who share both -- family members in the
    same case (two witnesses with the same surname and role) is the
    concrete failure this guards against, not a hypothetical one."""

    entity_id: int
    name: str
    role: str
    identifying_span: str
    source_id: int
    source_title: str


@dataclass(frozen=True)
class ProposedEntity:
    """Raw model output -- nothing here is trusted yet.
    packages/research/entity_extraction.py does span-location, role
    validation, and matched_entity_id verification before any of this
    becomes an Entity/EntityMatch row. role is a plain string, not an enum
    instance, same reasoning as ProposedClaim.claim_type/category in
    llm_provider.py: entity_extraction.py is the only place that maps it
    onto a real EntityRole value, and it does so defensively.

    matched_entity_id is the model's match-or-new decision: one of the
    ids it was shown in known_entities, or None for a new entity.
    entity_extraction.py re-checks this defensively -- rejected if it
    isn't None and isn't one of the ids actually sent in that call, the
    same "provider schema enforcement might be weaker than expected"
    posture already applied to claim_type elsewhere.

    match_rationale is the model's short free-text explanation of why
    this mention is matched_entity_id -- its content is not validated or
    located, read by a human, never trusted by code, the same role
    RejectedClaim's reason strings play in claim extraction. Its
    *presence*, though, is enforced by entity_extraction.py: rejected
    unless it is None exactly when matched_entity_id is None -- there is
    nothing to explain about a founding match, and a non-founding match
    with no stated rationale would undercut the entire reason
    EntityMatch.match_rationale exists (see docs/SCHEMA.md)."""

    name: str
    role: str
    identifying_span: str
    matched_entity_id: int | None
    match_rationale: str | None


class EntityExtractionProviderError(Exception):
    """Base class for provider failures that entity_extraction.py should
    treat as "this source's extraction failed," not a crash."""


class TruncatedEntityExtractionError(EntityExtractionProviderError):
    """The model's response was cut off before completing valid output
    (e.g. an output-token ceiling hit on a source naming many people).
    Implementations are expected to retry once at a higher output-token
    ceiling themselves before raising this -- the interface promises an
    entity list or a clear failure, not a retry-count."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"entity extraction response was truncated: {detail}")


class EntityExtractionProvider(Protocol):
    async def extract_entities(
        self, source_text: str, known_entities: list[KnownEntity]
    ) -> list[ProposedEntity]:
        """known_entities is the subject's existing entities (see
        KnownEntity), passed so the model can decide, per mention, whether
        it matches an existing one or is someone new -- see
        docs/SCHEMA.md's "Entity extraction" section for why this is asked
        of the model rather than computed. Raises
        EntityExtractionProviderError (or a subclass) on failure; never
        returns a partial/best-effort list."""
        ...
