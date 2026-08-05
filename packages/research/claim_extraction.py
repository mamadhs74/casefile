"""Turns a persisted Source's text into Claim/ClaimSource rows --
docs/SOURCING.md's claim table. Provider-agnostic: talks only to
packages.research.llm_provider.ClaimExtractionProvider, never a specific
SDK -- see that module's docstring for why.

Every surviving claim is created narratable=False here, in addition to
packages/db/listeners.py's enforcement -- belt-and-suspenders, same
posture as every other invariant in this schema layer.

Order, all before any persistence:

1. Skip entirely if this Source already has any linked Claim, unless
   force=True -- re-extraction is not deterministic (the same source
   extracted twice will not produce the same claims), and a prior claim
   may already be narratable and cited by a published episode's
   EpisodeClaim. force=True does not delete or merge anything; it adds a
   second batch of candidate claims alongside the first, for a human to
   reconcile -- see docs/SCHEMA.md.
2. Ask the provider for proposed claims, source.tier passed as context.
3. For each proposed claim, in order:
   a. Reject if quoted_span is blank.
   b. Reject if quoted_span is not found in the source's text once
      whitespace is normalized -- every run of whitespace (space,
      newline, tab) matches any run of whitespace, but every other
      character must match literally. This is not a relaxation of the
      hallucination check: a substituted word, an invented clause, or
      reordered content still fails outright, because those aren't
      whitespace. What it fixes is real: PDF extraction preserves the
      source document's physical line breaks, so a quote spanning even
      one line-wrap in the original PDF contains a `\n` mid-sentence that
      no model reproduces (nor should it -- reproducing arbitrary
      column-width line breaks isn't "more faithful," it's reproducing a
      rendering artifact). A byte-exact rule rejects that quote for a
      reason that has nothing to do with whether the claim is true or the
      citation is real. See docs/SCHEMA.md for the investigation that
      found this: on a real court-opinion PDF, every substantive claim
      was rejected this way and only a one-line filing-date stamp
      survived, which is a corpus-wide bias against exactly the sentences
      an episode would use, not evidence of a well-functioning filter.
   c. Reject if the located span exceeds MAX_QUOTED_SPAN_CHARS -- a
      "supporting passage" longer than that isn't reviewable in seconds.
      Measured on the real matched span in the source, which can be
      longer than the model's own quote once its whitespace expands back
      to the source's actual line breaks.
   d. Reject if claim_type or category isn't a recognized value. The
      provider's own structured-output schema should make this
      unreachable; this check is defensive, not load-bearing.
   e. Derive confidence mechanically from claim_type, rather than asking
      the model for both independently -- see docs/SCHEMA.md for why
      this pairing is fixed instead of modeled as two free axes.
4. Persist Claim + exactly one ClaimSource per surviving claim.
   dry_run=True runs every step above but skips persistence, returning
   what would have been created.
5. If zero claims survived and the source is Tier A, flag it in the
   result -- not an error (a source can legitimately have no extractable
   facts), but a Tier A source producing nothing is more surprising than
   a Tier B one and worth a human's attention.

This writes exactly one ClaimSource per claim. A claim genuinely
synthesized from two different sources is out of scope for this module --
see docs/SCHEMA.md: that's a later, currently-unbuilt reconciliation
step's job, not something a single-source extraction pass does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, select

from packages.db.models import Claim, ClaimSource, Source
from packages.domain.enums import TIER_A_SOURCE_TIERS, ClaimCategory, ClaimConfidence, ClaimType
from packages.domain.spans import locate_span
from packages.research.llm_provider import ClaimExtractionProvider, ProposedClaim

MAX_QUOTED_SPAN_CHARS = 800

# SOURCING.md's `type`/`confidence` fields look independent but overlap in
# what they're meant to capture (see docs/SCHEMA.md); for extraction this
# pairing is fixed, not asked of the model as two free choices.
_CONFIDENCE_BY_CLAIM_TYPE: dict[ClaimType, ClaimConfidence] = {
    ClaimType.FACT: ClaimConfidence.ESTABLISHED,
    ClaimType.CONTEMPORANEOUS_REPORT: ClaimConfidence.REPORTED,
    ClaimType.INFERENCE: ClaimConfidence.REPORTED,
}


@dataclass(frozen=True)
class RejectedClaim:
    """quoted_span is what the model attempted, kept even on rejection --
    a rejected claim is the thing most worth being able to inspect (was
    this a real near-miss, a genuine invention, or something the matching
    rule got wrong?), and a reason string alone can't answer that."""

    assertion: str
    quoted_span: str
    reason: str  # "empty_quote" | "quote_not_found" | "span_too_long" |
    # "invalid_claim_type" | "invalid_category"


@dataclass(frozen=True)
class ExtractedClaim:
    """One claim this run created, or would create in dry-run mode.
    claim_id is None exactly when dry_run=True -- nothing was persisted."""

    claim_id: int | None
    statement: str
    category: ClaimCategory
    claim_type: ClaimType
    confidence: ClaimConfidence
    date_anchor: str | None
    quoted_span: str
    span_start: int
    span_end: int


@dataclass(frozen=True)
class ClaimExtractionResult:
    source_id: int
    skipped_already_extracted: bool = False
    claims: list[ExtractedClaim] = field(default_factory=list)
    rejected: list[RejectedClaim] = field(default_factory=list)
    zero_claims_on_tier_a_source: bool = False


@dataclass(frozen=True)
class _ValidatedCandidate:
    claim_type: ClaimType
    category: ClaimCategory
    span_start: int
    span_end: int
    quoted_span: str  # source_text[span_start:span_end] -- the real
    # matched text, including the source's own line breaks if any, not
    # the model's normalized version. Keeps quoted_span consistent with
    # the offsets it's stored alongside.


async def extract_claims_for_source(
    session: Session,
    source: Source,
    provider: ClaimExtractionProvider,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> ClaimExtractionResult:
    assert source.id is not None
    source_id = source.id

    if not force and _has_existing_claims(session, source_id):
        return ClaimExtractionResult(source_id=source_id, skipped_already_extracted=True)

    source_text = Path(source.text_path).read_text(encoding="utf-8")
    proposed = await provider.extract_claims(source_text, source.tier.value)

    extracted: list[ExtractedClaim] = []
    rejected: list[RejectedClaim] = []

    for candidate in proposed:
        outcome = _validate(candidate, source_text)
        if isinstance(outcome, str):
            rejected.append(
                RejectedClaim(
                    assertion=candidate.assertion,
                    quoted_span=candidate.quoted_span,
                    reason=outcome,
                )
            )
            continue

        confidence = _CONFIDENCE_BY_CLAIM_TYPE[outcome.claim_type]
        claim_id: int | None = None

        if not dry_run:
            claim = Claim(
                subject_id=source.subject_id,
                statement=candidate.assertion,
                category=outcome.category,
                claim_type=outcome.claim_type,
                confidence=confidence,
                date_anchor=candidate.date_anchor,
                narratable=False,  # hardcoded, not derived -- see module docstring
            )
            session.add(claim)
            session.commit()
            session.refresh(claim)
            assert claim.id is not None
            claim_id = claim.id

            session.add(
                ClaimSource(
                    claim_id=claim_id,
                    source_id=source_id,
                    quoted_span=outcome.quoted_span,
                    span_start=outcome.span_start,
                    span_end=outcome.span_end,
                )
            )
            session.commit()

        extracted.append(
            ExtractedClaim(
                claim_id=claim_id,
                statement=candidate.assertion,
                category=outcome.category,
                claim_type=outcome.claim_type,
                confidence=confidence,
                date_anchor=candidate.date_anchor,
                quoted_span=outcome.quoted_span,
                span_start=outcome.span_start,
                span_end=outcome.span_end,
            )
        )

    zero_claims_on_tier_a = len(extracted) == 0 and source.tier in TIER_A_SOURCE_TIERS

    return ClaimExtractionResult(
        source_id=source_id,
        claims=extracted,
        rejected=rejected,
        zero_claims_on_tier_a_source=zero_claims_on_tier_a,
    )


def _has_existing_claims(session: Session, source_id: int) -> bool:
    return (
        session.exec(select(ClaimSource).where(ClaimSource.source_id == source_id)).first()
        is not None
    )


def _validate(candidate: ProposedClaim, source_text: str) -> _ValidatedCandidate | str:
    """Returns the validated span/enum values, or a short rejection-reason
    string identifying which check failed."""
    quote = candidate.quoted_span
    if not quote.strip():
        return "empty_quote"

    span = locate_span(quote, source_text)
    if span is None:
        return "quote_not_found"
    span_start, span_end = span

    if span_end - span_start > MAX_QUOTED_SPAN_CHARS:
        return "span_too_long"

    try:
        claim_type = ClaimType(candidate.claim_type)
    except ValueError:
        return "invalid_claim_type"
    if claim_type not in _CONFIDENCE_BY_CLAIM_TYPE:
        # DISPUTED is a real ClaimType value elsewhere in the schema, but
        # never a valid extraction output -- see llm_provider.py.
        return "invalid_claim_type"

    try:
        category = ClaimCategory(candidate.category)
    except ValueError:
        return "invalid_category"

    return _ValidatedCandidate(
        claim_type=claim_type,
        category=category,
        span_start=span_start,
        span_end=span_end,
        quoted_span=source_text[span_start:span_end],
    )
