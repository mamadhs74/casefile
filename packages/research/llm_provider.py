"""Provider interface for claim extraction.

One protocol, one implementation (packages/research/gemini_provider.py) --
free-tier LLM providers have a documented history of silently deleting or
replacing models (see docs/SCHEMA.md), so nothing in
packages/research/claim_extraction.py imports a provider SDK directly.
Swapping providers later means adding a class here that satisfies
ClaimExtractionProvider, not touching extraction logic.

Deliberately minimal: one method, one input shape, one output shape. Not
built out with retry/rate-limit/cost-tracking hooks up front -- add those
if and when a second implementation actually needs them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProposedClaim:
    """Raw model output -- nothing here is trusted yet.
    packages/research/claim_extraction.py does verbatim-quote-location,
    span-length, and enum validation before any of this becomes a Claim
    row. claim_type and category are plain strings, not enum instances,
    so a provider can never accidentally import packages.domain.enums
    and this module stays free of any dependency in that direction --
    claim_extraction.py is the only place that maps these strings onto
    real enum values, and it does so defensively (an unrecognized value
    is a rejected claim, not a crash)."""

    assertion: str
    quoted_span: str
    claim_type: str
    category: str
    date_anchor: str | None


class ExtractionProviderError(Exception):
    """Base class for provider failures that claim_extraction.py should
    treat as "this source's extraction failed," not a crash."""


class TruncatedExtractionError(ExtractionProviderError):
    """The model's response was cut off before completing valid output
    (e.g. an output-token ceiling hit on an unusually claim-dense
    source). Implementations are expected to retry once at a higher
    output-token ceiling themselves before raising this -- the interface
    promises a claim list or a clear failure, not a retry-count."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"extraction response was truncated: {detail}")


class ClaimExtractionProvider(Protocol):
    async def extract_claims(
        self, source_text: str, source_tier: str
    ) -> list[ProposedClaim]:
        """source_tier is plain-language context (e.g. "primary_record",
        "contemporaneous", "unverified") passed so the model can apply
        the tier-based FACT vs CONTEMPORANEOUS_REPORT asymmetry -- see
        docs/SCHEMA.md's claim-extraction section. Implementations must
        constrain their own structured-output mechanism to never emit
        anything but {"fact", "contemporaneous_report", "inference"} for
        claim_type -- DISPUTED is reserved for a future cross-source
        reconciliation stage that doesn't exist yet, and a single source's
        text can never justify it. Raises ExtractionProviderError (or a
        subclass) on failure; never returns a partial/best-effort list."""
        ...
