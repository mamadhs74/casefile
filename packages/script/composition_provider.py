"""Provider interface for step 3's composition pass -- turning one
section's allocated claims into prose. Same shape as
packages/research/entity_provider.py: one protocol, deliberately minimal,
no retry/rate-limit/cost-tracking hooks up front. Nothing in
packages/script/composition.py should import a provider SDK directly, so
swapping providers later means adding a class here that satisfies
CompositionProvider, not touching the orchestration logic.

This is a fundamentally different verifiability shape than claim
extraction. claim_extraction.py's quoted_span is structurally verifiable
-- a human (or code) can locate the exact substring in the source text
and confirm it exists, character for character. There is no equivalent
mechanism here: composed prose is *new* text derived from the claims, not
copied from anywhere, so there is nothing to locate. Rule 1 ("never
introduce a fact absent from the claim set") and preserving claim_type
distinctions are prompt-level constraints this module asks the model to
follow; nothing downstream of the provider call can structurally verify
either one. That is a human's job at review time, the same boundary
claim_extraction.py's own docstring already draws between "structurally
verifiable" and "semantically verifiable" -- restated here because it is
easy to assume the interface buys more safety than it does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ClaimForComposition:
    """One claim as composition input. claim_type/confidence are plain
    strings, not enum instances -- same reasoning as ProposedClaim in
    packages/research/llm_provider.py: this module stays free of any
    dependency on packages.domain.enums, and the caller (not the
    provider) is the one place that already holds real enum values and
    is responsible for stringifying them.

    thesis_bearing drives the elaborate-vs-one-sentence split (sec 3.4).
    This is deliberately not scoped to Sequence specifically -- a Ground
    or Resolution claim can be thesis-bearing too and gets the same
    elaboration inside its own section, per how thesis_bearing and
    section were decided to be orthogonal (docs/SCHEMA.md).

    word_target is the number this split actually cashes out to: sec
    3.4's 60/40 section-budget split, divided evenly within each of the
    two groups, computed by packages/script/chronological.py alongside
    SectionWordCounts (it needs the section's own claim list and that
    section's own budget, both only in scope there). Before this field
    existed, the provider only ever received thesis_bearing as a bare
    boolean plus one section-level total -- nothing told it how many
    claims were sharing that total or how unevenly to split it, which is
    why the first real run under-filled every section. See
    gemini_composition_provider.py's system instruction for how this
    number is used in the actual request."""

    claim_id: int
    statement: str
    claim_type: str
    confidence: str
    date_anchor: str | None
    thesis_bearing: bool
    word_target: int


@dataclass(frozen=True)
class ComposedSection:
    """Raw model output -- nothing here is verified, see module
    docstring. text is the section's composed prose, nothing else;
    word-count reporting against budget (rule 4) is computed by the
    caller from this text, not returned by the provider."""

    text: str


class CompositionProviderError(Exception):
    """Base class for provider failures that a caller should treat as
    "this section's composition failed," not a crash."""


class TruncatedCompositionError(CompositionProviderError):
    """The model's response was cut off before completing valid output.
    Implementations are expected to retry once at a higher output-token
    ceiling themselves before raising this -- same contract as
    TruncatedExtractionError/TruncatedEntityExtractionError."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"composition response was truncated: {detail}")


class CompositionProvider(Protocol):
    async def compose_section(
        self,
        claims: list[ClaimForComposition],
        thesis: str,
        word_budget: int,
    ) -> ComposedSection:
        """claims is the section's already-allocated claim list (empty
        for Return -- see docs/ARCHITECTURES.md sec 3.6 -- which is a
        different task, paraphrasing thesis, not composing from claims,
        not a degenerate case of the same one). thesis is always
        Episode.thesis, passed to every section for tonal consistency
        (docs/SOURCING.md: "the generator receives the thesis text and
        the flags"). word_budget is a target the model should aim for,
        not a hard constraint -- rule 4 stays checked-and-reported by the
        caller, never enforced here. Raises CompositionProviderError (or
        a subclass) on failure; never returns partial/best-effort text."""
        ...
