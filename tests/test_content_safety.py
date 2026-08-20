"""packages/domain/content_safety.py's rejection filter -- built after
subject 8 held 17 real claims identifying a minor sexual-assault victim
indirectly through her named mother (docs/HANDOFF.md,
scripts/delete_subject8_contaminated_claims.py). Covers check_text()
directly, the logging contract, and the unconditional Claim.before_insert
floor (packages/db/listeners.py). The "source content" half of the
filter, enforced inside claim_extraction.py's pipeline, is covered in
tests/test_claim_extraction.py instead, alongside the rest of that
module's rejection-reason tests.
"""

from __future__ import annotations

import logging

import pytest
from sqlmodel import Session

from packages.db.models import Claim
from packages.domain.content_safety import ClaimContentRejectedError, check_text, log_rejection
from packages.domain.enums import ClaimCategory, ClaimConfidence, ClaimType
from tests.factories import make_subject


def _persist_subject(session: Session, strategy_id: int) -> int:
    subject = make_subject(strategy_id)
    session.add(subject)
    session.commit()
    session.refresh(subject)
    assert subject.id is not None
    return subject.id


# --------------------------------------------------------------------
# check_text() -- pure function, no DB
# --------------------------------------------------------------------


def test_clean_claim_text_passes() -> None:
    assert check_text("The jury returned a verdict of not guilty.") is None


def test_direct_term_is_rejected() -> None:
    match = check_text(
        "Long appealed his conviction for first-degree criminal sexual "
        "conduct and kidnapping."
    )
    assert match is not None
    assert "criminal sexual conduct" in match.reason


def test_bare_csc_shorthand_is_rejected() -> None:
    """The real claim that forced this term into the list even without
    an explicit 'minor'/'child' in the same sentence -- see
    SEXUAL_OFFENSE_MINOR_TERMS' own comment on why."""
    match = check_text("The court severed the murder charges from the CSC and kidnapping charges.")
    assert match is not None


def test_relative_identification_with_sexual_offense_context_is_rejected() -> None:
    match = check_text(
        "Marlene Haywood's minor child testified that Long touched her "
        "inappropriately and later sexually assaulted her at gunpoint."
    )
    assert match is not None
    assert "named relative" in match.reason


def test_relative_identification_without_sexual_offense_context_passes() -> None:
    """The relative-identification pattern alone is not enough -- an
    ordinary claim naming someone's child in an unrelated context must
    not be swept up."""
    assert check_text("Marlene Haywood's son graduated from high school in 2019.") is None


@pytest.mark.parametrize("bad_input", [None, "", "   ", 12345, ["not", "a", "string"]])
def test_fail_closed_on_unevaluable_input(bad_input: object) -> None:
    match = check_text(bad_input)
    assert match is not None
    assert "cannot evaluate" in match.reason


# --------------------------------------------------------------------
# log_rejection() -- the logging contract
# --------------------------------------------------------------------


def test_rejection_is_logged_with_source_and_reason(caplog: pytest.LogCaptureFixture) -> None:
    match = check_text("first-degree criminal sexual conduct")
    assert match is not None

    with caplog.at_level(logging.WARNING, logger="packages.domain.content_safety"):
        log_rejection(
            subject_id=8,
            source_label="source_id=5 (courtlistener.com)",
            statement="first-degree criminal sexual conduct",
            match=match,
        )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING
    assert "source_id=5" in record.message
    assert "courtlistener.com" in record.message
    assert match.reason in record.message


# --------------------------------------------------------------------
# Claim.before_insert -- the unconditional floor
# --------------------------------------------------------------------


def test_listener_rejects_unsafe_claim_at_insert(session: Session, strategy_id: int) -> None:
    subject_id = _persist_subject(session, strategy_id)
    claim = Claim(
        subject_id=subject_id,
        statement="Long appealed his conviction for criminal sexual conduct with a minor.",
        category=ClaimCategory.LEGAL_OUTCOME,
        claim_type=ClaimType.FACT,
        confidence=ClaimConfidence.ESTABLISHED,
        narratable=False,
    )
    session.add(claim)
    with pytest.raises(ClaimContentRejectedError):
        session.commit()


def test_listener_allows_clean_claim_at_insert(session: Session, strategy_id: int) -> None:
    subject_id = _persist_subject(session, strategy_id)
    claim = Claim(
        subject_id=subject_id,
        statement="The jury returned a verdict of not guilty.",
        category=ClaimCategory.LEGAL_OUTCOME,
        claim_type=ClaimType.FACT,
        confidence=ClaimConfidence.ESTABLISHED,
        narratable=False,
    )
    session.add(claim)
    session.commit()  # must not raise
    assert claim.id is not None
