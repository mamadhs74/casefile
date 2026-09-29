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
      whitespace is normalized and case differences are ignored -- every
      run of whitespace (space, newline, tab) matches any run of
      whitespace, and a letter matches its own upper/lowercase form, but
      every other character must match literally. This is not a
      relaxation of the hallucination check: a substituted word, an
      invented clause, or reordered content still fails outright,
      because those aren't whitespace or case. What whitespace-tolerance
      fixes is real: PDF extraction preserves the source document's
      physical line breaks, so a quote spanning even one line-wrap in
      the original PDF contains a `\n` mid-sentence that no model
      reproduces (nor should it -- reproducing arbitrary column-width
      line breaks isn't "more faithful," it's reproducing a rendering
      artifact). A byte-exact rule rejects that quote for a reason that
      has nothing to do with whether the claim is true or the citation
      is real. See docs/SCHEMA.md for the investigation that found this:
      on a real court-opinion PDF, every substantive claim was rejected
      this way and only a one-line filing-date stamp survived, which is
      a corpus-wide bias against exactly the sentences an episode would
      use, not evidence of a well-functioning filter. Case-tolerance
      fixes the same class of problem, found later: a real Groq
      extraction lowercased a sentence-initial word ("the deal" for
      "The deal") reproducing an otherwise-perfect quote, and rejecting
      it cost the one candidate that falsified episode 1's thesis
      (docs/HANDOFF.md #48/#49) over a difference that isn't content.
      The persisted quoted_span is still sliced from source_text by the
      located (start, end) offsets, so it always carries the source's
      own real casing, never the model's -- case-insensitivity only
      widens what can be *found*, it never changes what gets *stored*.
      This uses a local, case-insensitive location function scoped to
      this module only -- packages/domain/spans.py's own locate_span
      (whitespace-tolerant, case-sensitive) is unchanged, since it also
      backs packages/db/listeners.py's Entity.living_evidence check
      (R8), a stricter invariant this task was not asked to loosen.
   c. Reject if the located span exceeds MAX_QUOTED_SPAN_CHARS -- a
      "supporting passage" longer than that isn't reviewable in seconds.
      Measured on the real matched span in the source, which can be
      longer than the model's own quote once its whitespace expands back
      to the source's actual line breaks.
   d. Reject if the assertion states a dollar amount, percentage, or
      magnitude-suffixed count (e.g. "$110 billion", "45%", "325
      million") that does not appear, once normalized, inside that
      claim's own located span. A claim can locate a real, verbatim
      passage and still smuggle in a number from elsewhere in the
      source -- a real finding, not a hypothetical: an assertion cited
      a $110 billion merger value while its own quoted_span was the
      unrelated trial-date sentence three sentences later, which never
      mentions that figure at all (docs/HANDOFF.md). Normalization
      treats "$110B" and "$110 billion" as the same figure (commas,
      "$", and "~" stripped; B/bn/billion and M/mn/million unified) so
      a shorthand restatement of the same number is never a false
      rejection -- see _figures_in's own docstring for exactly what
      counts as a figure. Plain integers, dates, and years are out of
      scope entirely: every branch of the pattern requires a "%", "$",
      or magnitude suffix to match at all, so "12 states" or "2027"
      never triggers this check in the first place, not because of a
      separate date-detection rule but because nothing about them looks
      like a figure to begin with.
   e. Reject if claim_type or category isn't a recognized value. The
      provider's own structured-output schema should make this
      unreachable; this check is defensive, not load-bearing.
   f. Derive confidence mechanically from claim_type, rather than asking
      the model for both independently -- see docs/SCHEMA.md for why
      this pairing is fixed instead of modeled as two free axes.
   g. Reject if the candidate's located span overlaps an existing
      ClaimSource for this source by at least
      DUPLICATE_SPAN_OVERLAP_THRESHOLD (90%) of the longer of the two
      spans -- this is what keeps force=True's "adds a second batch,
      never deletes or merges" contract (step 1 above) from also
      meaning "duplicates every claim that gets proposed again." force
      exists so a human can add genuinely new claims a first pass
      missed, not to multiply near-identical Claim+ClaimSource pairs
      each time the same passage gets re-proposed with a one-character-
      different boundary. Exact-match was tried first and measured
      insufficient: a real forced re-run produced 12 candidates, of
      which only 4 shared an exact span with an existing claim, but 10
      of the 12 turned out to restate a fact already in the DB, off by
      one trailing period or a slightly wider/narrower quote boundary
      (docs/HANDOFF.md). Overlap-ratio, not raw character overlap,
      because two genuinely different facts drawn from the same long
      sentence can share a real, small amount of text without being
      duplicates of each other -- ratio against the longer span is what
      lets a short subset-quote inside a long one register as highly
      overlapping while two partially-overlapping-but-otherwise-
      distinct quotes don't. Checked against every ClaimSource already
      in the DB for this source_id, plus every span already accepted
      earlier in this same run. A fresh source with nothing extracted
      yet has no existing spans, so this step never rejects anything on
      a first pass.
   h. Reject if packages.domain.content_safety.check_text() matches
      either the candidate's assertion or its located quoted_span --
      this is the "source content" half of that filter (the other
      half, statement-only, is enforced unconditionally at
      packages/db/listeners.py's Claim.before_insert, which this check
      does not replace, it runs in addition to it, earlier). Logged via
      log_rejection with this source's id and domain. A rejection here
      is not an error -- extraction continues with the next candidate.
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

import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, select

from packages.db.models import Claim, ClaimSource, Source
from packages.domain.content_safety import check_text, log_rejection
from packages.domain.enums import TIER_A_SOURCE_TIERS, ClaimCategory, ClaimConfidence, ClaimType
from packages.research.llm_provider import ClaimExtractionProvider, ProposedClaim

MAX_QUOTED_SPAN_CHARS = 800

# See module docstring step 3g for why this is overlap-ratio, not
# exact-match -- measured against a real forced re-run before picking
# 0.90, not chosen a priori.
DUPLICATE_SPAN_OVERLAP_THRESHOLD = 0.90

# Word/abbreviation forms map to a single canonical letter so "$110B"
# and "$110 billion" compare equal -- see _figures_in's own docstring.
# Matched case-insensitively; a stray lowercase "b"/"m"/"k" immediately
# after a number is treated the same as its uppercase form, a
# deliberate heuristic looseness rather than exhaustive correctness
# (same posture as this module's other pattern-matching checks).
_MAGNITUDE_CANONICAL: dict[str, str] = {
    "b": "B", "bn": "B", "billion": "B",
    "m": "M", "mn": "M", "million": "M",
    "k": "K", "thousand": "K",
}
_MAGNITUDE_WORD = r"(?:billion|bn|million|mn|thousand|b|m|k)"

# Three alternatives, tried in order: a percentage ("44%", "44
# percent", "44 per cent" all normalize the same way), a dollar figure
# (magnitude suffix optional -- "$500" alone is still a figure worth
# checking), or a bare magnitude-suffixed count with no currency sign
# ("325M subscribers", "180 million viewers"). A bare number with no
# magnitude, no "$", and no "%"/"percent" never matches any branch --
# that's what keeps "12 states", "5 days", and "2027" out of scope
# without a separate date/year-detection rule.
_FIGURE_PATTERN = re.compile(
    rf"""
    (?P<percent_num>\d+(?:\.\d+)?)\s*(?:%|per\s*cent)
    |
    \$\s*~?\s*(?P<dollar_num>[\d,]+(?:\.\d+)?)(?:\s*(?P<dollar_mag>{_MAGNITUDE_WORD}))?\b
    |
    ~?(?P<bare_num>[\d,]+(?:\.\d+)?)\s*(?P<bare_mag>{_MAGNITUDE_WORD})\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def _normalize_figure_number(raw: str) -> str:
    """Strips "$"/","/"~" and collapses a trailing ".0" -- just enough
    to compare "110" against "110.0" or "110,000" against "110000" as
    the same number, not a general numeric-equality library."""
    cleaned = raw.replace(",", "").replace("$", "").replace("~", "")
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned or "0"


def _figures_in(text: str) -> set[tuple[str, str]]:
    """Every percentage, dollar figure, or magnitude-suffixed bare count
    in text, normalized to (number, magnitude) so pure formatting
    differences ("$110B" vs "$110 billion", "45M" vs "45 million")
    compare equal. magnitude is "%" for a percentage, "" for a dollar
    figure with no magnitude word, or "B"/"M"/"K" otherwise. See
    _FIGURE_PATTERN's own comment for what counts as a figure at all --
    plain integers, dates, and years never do."""
    figures: set[tuple[str, str]] = set()
    for match in _FIGURE_PATTERN.finditer(text):
        if match.group("percent_num"):
            figures.add((_normalize_figure_number(match.group("percent_num")), "%"))
        elif match.group("dollar_num"):
            magnitude = match.group("dollar_mag")
            canonical = _MAGNITUDE_CANONICAL[magnitude.lower()] if magnitude else ""
            figures.add((_normalize_figure_number(match.group("dollar_num")), canonical))
        elif match.group("bare_num"):
            magnitude = match.group("bare_mag")
            number = _normalize_figure_number(match.group("bare_num"))
            figures.add((number, _MAGNITUDE_CANONICAL[magnitude.lower()]))
    return figures


def _unsupported_figures(assertion: str, quoted_span: str) -> set[tuple[str, str]]:
    """Figures present in the assertion but absent from the claim's own
    located quoted_span -- see claim_extraction_for_source's module
    docstring, step 3d."""
    return _figures_in(assertion) - _figures_in(quoted_span)


def _locate_span_case_insensitive(quote: str, source_text: str) -> tuple[int, int] | None:
    """Same whitespace-tolerant approach as packages.domain.spans.locate_span
    (built from quote's own whitespace-delimited tokens, escaped, joined
    by \\s+, searched directly against source_text so the real offsets
    come straight from the match), plus case-insensitivity -- see module
    docstring step 3b for why this module doesn't reuse the shared
    function as-is. Returns source_text's own (start, end); the caller
    slices source_text[start:end] to get the source's real casing back,
    never the model's."""
    tokens = quote.split()
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    match = re.search(pattern, source_text, re.IGNORECASE)
    if match is None:
        return None
    return match.start(), match.end()

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
    # "assertion_figure_not_in_quote" | "invalid_claim_type" |
    # "invalid_category" | "duplicate_span" | "content_safety_rejected"


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
    seen_spans = _existing_span_set(session, source_id)

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

        # Step 3g (module docstring) -- force=True must not duplicate a
        # claim whose span sufficiently overlaps one already backing a
        # claim for this source. seen_spans is seeded from the DB and
        # grows only as this run actually accepts candidates (below,
        # after content-safety) -- checked here first so a candidate
        # doesn't pay for a span a different, since-rejected candidate
        # merely attempted.
        span_key = (outcome.span_start, outcome.span_end)
        if _is_duplicate_span(span_key, seen_spans):
            rejected.append(
                RejectedClaim(
                    assertion=candidate.assertion,
                    quoted_span=candidate.quoted_span,
                    reason="duplicate_span",
                )
            )
            continue

        # "source content" half of packages.domain.content_safety's filter
        # -- checked against both the candidate's own statement and the
        # real, located source text backing it, only now that both are
        # known good (a candidate that failed span-matching above has no
        # reliable quoted_span to check). Not an error -- rejected and
        # logged, extraction continues with the next candidate.
        safety_match = check_text(candidate.assertion) or check_text(outcome.quoted_span)
        if safety_match is not None:
            log_rejection(
                subject_id=source.subject_id,
                source_label=f"source_id={source_id} ({source.domain})",
                statement=candidate.assertion,
                match=safety_match,
            )
            rejected.append(
                RejectedClaim(
                    assertion=candidate.assertion,
                    quoted_span=candidate.quoted_span,
                    reason="content_safety_rejected",
                )
            )
            continue

        # Only now, once this candidate will actually be created below --
        # a candidate rejected above (content-safety or otherwise) never
        # occupies its span, so a later, distinct candidate that happens
        # to locate the same span is still free to use it.
        seen_spans.add(span_key)

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


def _existing_span_set(session: Session, source_id: int) -> set[tuple[int, int]]:
    """Every (span_start, span_end) already persisted for this source --
    empty on a source with nothing extracted yet. See module docstring
    step 3g for why this exists (force=True dedupe)."""
    rows = session.exec(select(ClaimSource).where(ClaimSource.source_id == source_id)).all()
    return {(row.span_start, row.span_end) for row in rows}


def _overlap_ratio(a: tuple[int, int], b: tuple[int, int]) -> float:
    """Overlapping character count divided by the LONGER of the two
    spans -- not the shorter, and not raw overlap length alone. Against
    the longer span, a short quote fully contained inside a much longer
    one still reads as highly overlapping (correct -- that's a
    restatement), while two long, mostly-distinct quotes that happen to
    share a short connecting phrase don't cross the threshold (also
    correct -- see module docstring step 3g)."""
    a_start, a_end = a
    b_start, b_end = b
    overlap = max(0, min(a_end, b_end) - max(a_start, b_start))
    longer = max(a_end - a_start, b_end - b_start)
    if longer == 0:
        return 0.0
    return overlap / longer


def _is_duplicate_span(candidate: tuple[int, int], existing: set[tuple[int, int]]) -> bool:
    return any(
        _overlap_ratio(candidate, other) >= DUPLICATE_SPAN_OVERLAP_THRESHOLD for other in existing
    )


def _validate(candidate: ProposedClaim, source_text: str) -> _ValidatedCandidate | str:
    """Returns the validated span/enum values, or a short rejection-reason
    string identifying which check failed."""
    quote = candidate.quoted_span
    if not quote.strip():
        return "empty_quote"

    span = _locate_span_case_insensitive(quote, source_text)
    if span is None:
        return "quote_not_found"
    span_start, span_end = span

    if span_end - span_start > MAX_QUOTED_SPAN_CHARS:
        return "span_too_long"

    real_quote = source_text[span_start:span_end]
    if _unsupported_figures(candidate.assertion, real_quote):
        return "assertion_figure_not_in_quote"

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
        quoted_span=real_quote,
    )
