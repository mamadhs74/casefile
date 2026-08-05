"""packages/research/claim_extraction.py: verbatim-quote verification,
claim_type/confidence/category validation, narratable=False, dry-run,
and the no-op-unless-forced re-extraction rule.

Uses a fake provider (packages.research.llm_provider.ClaimExtractionProvider
is a Protocol precisely so tests never need a real Gemini call).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from packages.db.models import Claim, ClaimSource, Source
from packages.domain.enums import ClaimConfidence, ClaimType, SourceTier
from packages.research.claim_extraction import (
    MAX_QUOTED_SPAN_CHARS,
    extract_claims_for_source,
)
from packages.research.llm_provider import ProposedClaim
from tests.factories import make_source, make_subject

SOURCE_TEXT = (
    "In March 1922, six people vanished from a small farmstead in Bavaria. "
    "Andreas Gruber, his wife, their widowed daughter, and her four children "
    "had not been seen for several days when a neighbor grew concerned and "
    "went to check on them. Investigators later determined the family had "
    "been killed."
)

# Mimics pypdf's real behavior: the original document's physical line wrap
# is preserved as a literal newline mid-sentence -- see docs/SCHEMA.md's
# claim-extraction section for the real court-PDF case this was found on.
PDF_STYLE_SOURCE_TEXT = (
    "In March 1922, six people vanished from a small farmstead in Bavaria. \n"
    "Andreas Gruber, his wife, their widowed \ndaughter, and her four children \n"
    "had not been seen for several days."
)


class _FakeProvider:
    def __init__(self, claims: list[ProposedClaim]) -> None:
        self._claims = claims
        self.calls = 0
        self.last_source_tier: str | None = None

    async def extract_claims(self, source_text: str, source_tier: str) -> list[ProposedClaim]:
        self.calls += 1
        self.last_source_tier = source_tier
        return self._claims


def _make_source(
    session: Session, subject_id: int, tmp_path: Path, **overrides: Any
) -> Source:
    if "text_path" not in overrides:
        text_path = tmp_path / "source.txt"
        text_path.write_text(SOURCE_TEXT, encoding="utf-8")
        overrides["text_path"] = str(text_path)
    overrides.setdefault("tier", SourceTier.RETROSPECTIVE)
    source = make_source(subject_id, **overrides)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


VALID_QUOTE = "Andreas Gruber, his wife, their widowed daughter"


def _valid_candidate(**overrides: Any) -> ProposedClaim:
    defaults: dict[str, Any] = dict(
        assertion="Andreas Gruber's family lived at the farmstead.",
        quoted_span=VALID_QUOTE,
        claim_type="fact",
        category="person",
        date_anchor=None,
    )
    defaults.update(overrides)
    return ProposedClaim(**defaults)


async def test_valid_claim_is_persisted_with_located_span(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate()])

    result = await extract_claims_for_source(session, source, provider)

    assert len(result.claims) == 1
    claim = result.claims[0]
    assert claim.claim_id is not None
    assert claim.span_start == SOURCE_TEXT.find(VALID_QUOTE)
    assert claim.span_end == claim.span_start + len(VALID_QUOTE)
    assert claim.claim_type == ClaimType.FACT
    assert claim.confidence == ClaimConfidence.ESTABLISHED

    persisted = session.get(Claim, claim.claim_id)
    assert persisted is not None
    assert persisted.narratable is False

    link = session.exec(
        select(ClaimSource).where(ClaimSource.claim_id == claim.claim_id)
    ).one()
    assert link.source_id == source.id
    assert link.quoted_span == VALID_QUOTE


async def test_source_tier_is_passed_to_provider_as_plain_string(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path, tier=SourceTier.PRIMARY_RECORD)
    provider = _FakeProvider([])

    await extract_claims_for_source(session, source, provider)

    assert provider.last_source_tier == "primary_record"


@pytest.mark.parametrize(
    ("claim_type", "expected_confidence"),
    [
        (ClaimType.FACT, ClaimConfidence.ESTABLISHED),
        (ClaimType.CONTEMPORANEOUS_REPORT, ClaimConfidence.REPORTED),
        (ClaimType.INFERENCE, ClaimConfidence.REPORTED),
    ],
)
async def test_confidence_is_derived_mechanically_from_claim_type(
    session: Session,
    strategy_id: int,
    tmp_path: Path,
    claim_type: ClaimType,
    expected_confidence: ClaimConfidence,
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate(claim_type=claim_type.value)])

    result = await extract_claims_for_source(session, source, provider)

    assert result.claims[0].confidence == expected_confidence


async def test_quote_not_found_verbatim_is_rejected_not_persisted(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider(
        [_valid_candidate(quoted_span="a sentence that never appears in the source")]
    )

    result = await extract_claims_for_source(session, source, provider)

    assert result.claims == []
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "quote_not_found"
    assert result.rejected[0].quoted_span == "a sentence that never appears in the source"
    assert session.exec(select(Claim)).all() == []


async def test_close_but_not_exact_quote_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """A near-paraphrase (one word inserted) must not slip past as a
    fuzzy match -- this is precisely the failure category the exact-
    substring check exists to catch, and the reason it matters more with
    a smaller model, not less: a smaller model will hallucinate or
    reword citations more often."""
    near_miss = "Andreas Gruber, his wife, and their widowed daughter"  # "and" inserted
    assert near_miss not in SOURCE_TEXT
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate(quoted_span=near_miss)])

    result = await extract_claims_for_source(session, source, provider)

    assert result.claims == []
    assert result.rejected[0].reason == "quote_not_found"


async def test_quote_matches_across_a_pdf_line_wrap(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """The regression this whole mechanism was built for: pypdf preserves
    the source PDF's physical line breaks, so a real, accurately-quoted
    passage that happens to span one line-wrap contains a newline the
    model has no reason to reproduce. Whitespace-normalized matching must
    still find it -- and the persisted quoted_span/span_start/span_end
    must reflect the source's actual text (embedded newline included),
    not the model's normalized version, since ClaimSource.quoted_span
    must equal source_text[span_start:span_end]."""
    model_quote = "Andreas Gruber, his wife, their widowed daughter, and her four children"
    # confirms the newline really blocks a literal (non-normalized) match
    assert model_quote not in PDF_STYLE_SOURCE_TEXT

    subject_id = _persist_subject(session, strategy_id)
    text_path = tmp_path / "pdf_source.txt"
    text_path.write_text(PDF_STYLE_SOURCE_TEXT, encoding="utf-8")
    source = _make_source(session, subject_id, tmp_path, text_path=str(text_path))
    provider = _FakeProvider([_valid_candidate(quoted_span=model_quote)])

    result = await extract_claims_for_source(session, source, provider)

    assert len(result.claims) == 1
    claim = result.claims[0]
    expected_span = PDF_STYLE_SOURCE_TEXT[claim.span_start : claim.span_end]
    assert claim.quoted_span == expected_span
    assert "\n" in claim.quoted_span  # the real source substring, not the model's normalized quote
    assert claim.quoted_span != model_quote


async def test_substituted_word_across_a_pdf_line_wrap_is_still_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """Requirement: whitespace tolerance must not let a real content
    change ride along with it. Same passage as the line-wrap test above,
    but "daughter" -> "son" -- must still fail even though the rest of
    the passage, including its line-wrap, would otherwise match."""
    substituted = "Andreas Gruber, his wife, their widowed son, and her four children"

    subject_id = _persist_subject(session, strategy_id)
    text_path = tmp_path / "pdf_source.txt"
    text_path.write_text(PDF_STYLE_SOURCE_TEXT, encoding="utf-8")
    source = _make_source(session, subject_id, tmp_path, text_path=str(text_path))
    provider = _FakeProvider([_valid_candidate(quoted_span=substituted)])

    result = await extract_claims_for_source(session, source, provider)

    assert result.claims == []
    assert result.rejected[0].reason == "quote_not_found"
    assert result.rejected[0].quoted_span == substituted


async def test_span_too_long_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    long_text = "This sentence repeats. " * 60  # comfortably over 800 chars
    assert len(long_text) > MAX_QUOTED_SPAN_CHARS
    subject_id = _persist_subject(session, strategy_id)
    text_path = tmp_path / "long_source.txt"
    text_path.write_text(long_text, encoding="utf-8")
    source = _make_source(session, subject_id, tmp_path, text_path=str(text_path))

    provider = _FakeProvider([_valid_candidate(quoted_span=long_text)])

    result = await extract_claims_for_source(session, source, provider)

    assert result.claims == []
    assert result.rejected[0].reason == "span_too_long"


async def test_empty_quote_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate(quoted_span="   ")])

    result = await extract_claims_for_source(session, source, provider)

    assert result.rejected[0].reason == "empty_quote"


async def test_disputed_claim_type_from_model_is_rejected_not_persisted(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """DISPUTED is a real ClaimType value elsewhere in the schema but must
    never come out of extraction -- a single source can't establish that
    sources disagree. Defensive: the provider's schema should already make
    this unreachable, but this proves the fallback catches it too."""
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate(claim_type="disputed")])

    result = await extract_claims_for_source(session, source, provider)

    assert result.claims == []
    assert result.rejected[0].reason == "invalid_claim_type"


async def test_invalid_category_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate(category="not_a_real_category")])

    result = await extract_claims_for_source(session, source, provider)

    assert result.rejected[0].reason == "invalid_category"


async def test_dry_run_persists_nothing(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate()])

    result = await extract_claims_for_source(session, source, provider, dry_run=True)

    assert len(result.claims) == 1
    assert result.claims[0].claim_id is None
    assert session.exec(select(Claim)).all() == []
    assert session.exec(select(ClaimSource)).all() == []


async def test_reextraction_without_force_is_a_noop_and_skips_the_provider_call(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate()])
    await extract_claims_for_source(session, source, provider)
    assert provider.calls == 1

    result = await extract_claims_for_source(session, source, provider)

    assert result.skipped_already_extracted is True
    assert provider.calls == 1  # not called again
    assert len(session.exec(select(Claim)).all()) == 1


async def test_forced_reextraction_adds_a_second_batch_without_touching_the_first(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate()])
    first = await extract_claims_for_source(session, source, provider)
    first_claim_id = first.claims[0].claim_id

    second = await extract_claims_for_source(session, source, provider, force=True)

    assert second.skipped_already_extracted is False
    assert len(second.claims) == 1
    assert second.claims[0].claim_id != first_claim_id
    all_claims = session.exec(select(Claim)).all()
    assert len(all_claims) == 2
    assert session.get(Claim, first_claim_id) is not None  # untouched, not deleted


async def test_zero_claims_on_tier_a_source_is_flagged(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path, tier=SourceTier.PRIMARY_RECORD)
    provider = _FakeProvider([])

    result = await extract_claims_for_source(session, source, provider)

    assert result.claims == []
    assert result.zero_claims_on_tier_a_source is True


async def test_zero_claims_on_non_tier_a_source_is_not_flagged(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path, tier=SourceTier.UNVERIFIED)
    provider = _FakeProvider([])

    result = await extract_claims_for_source(session, source, provider)

    assert result.zero_claims_on_tier_a_source is False


def _persist_subject(session: Session, strategy_id: int) -> int:
    subject = make_subject(strategy_id)
    session.add(subject)
    session.commit()
    session.refresh(subject)
    assert subject.id is not None
    return subject.id
