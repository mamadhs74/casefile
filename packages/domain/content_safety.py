"""Content-safety rejection filter -- CLAUDE.md's R7 (living victims
and named individuals) and basic safety, enforced as code, not
editorial discretion after the fact. Built because subject 8 held 17
claims from a real South Carolina appellate opinion (State v. Antonio
Long) identifying a minor sexual-assault victim indirectly through her
named mother, sitting in the corpus for an extended period before
anyone caught it by hand -- see docs/HANDOFF.md and
scripts/delete_subject8_contaminated_claims.py, the cleanup this filter
exists to make unnecessary going forward.

TWO ENFORCEMENT POINTS, not one, because they see different data at
different times:

1. packages/db/listeners.py's Claim.before_insert -- checks
   Claim.statement only. This is the actual, unconditional floor: no
   code path can create a Claim row without going through the ORM's
   insert hook, so this check cannot be skipped by a strategy, a flag,
   or an ingestion path nobody has written yet. It cannot check
   "source content" because ClaimSource doesn't exist until after the
   Claim it references does (FK ordering -- see docs/SCHEMA.md's
   narratable-invariant section for the same constraint on a different
   listener).
2. packages/research/claim_extraction.py's _validate() -- checks both
   the candidate's assertion (statement) and its located quoted_span
   (source content), before either a Claim or a ClaimSource row is
   ever constructed. This is where "source content" actually gets
   checked, for the one real ingestion path that exists today.

Honest limit of this design, not hidden: a future ingestion path that
never calls check_text() against its own source content only gets the
statement-level floor from (1). (1) is unconditional by construction;
(2) is unconditional only for code that goes through
claim_extraction.py's _validate(). Recorded here so this isn't assumed
to be stronger than it is.

FAIL CLOSED: check_text() treats anything it cannot evaluate as a
match, not a pass -- empty or non-string input is itself a rejection,
never a silent pass-through.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Reviewable and extendable in one place, per the task this was built
# under. Deliberately phrases naming the offense (and, for most
# entries, the victim's minority) together -- a bare word like "minor"
# or "sexual" alone would false-positive on ordinary legal-outcome and
# procedural claims constantly.
#
# "criminal sexual conduct" and "csc" are the two exceptions, kept
# unqualified by "minor"/"child" on purpose: they're the exact
# statutory name and shorthand for the charge in the case this filter
# was built from, and not every sentence about that case repeated the
# victim's age -- one of the real claims that had to be caught read
# "...sever the murder charges from the CSC and kidnapping charges,"
# no "minor" anywhere in it. The accepted tradeoff: this also rejects
# adult-victim CSC claims from unrelated cases. Narrowing that later,
# if it proves too broad in practice, is a one-line edit here.
SEXUAL_OFFENSE_MINOR_TERMS: frozenset[str] = frozenset(
    {
        "criminal sexual conduct with a minor",
        "sexual abuse of a minor",
        "sexual abuse of a child",
        "sexually abused a minor",
        "sexually abused a child",
        "sexual assault of a minor",
        "sexual assault of a child",
        "sexually assaulted a minor",
        "sexually assaulted a child",
        "statutory rape",
        "child sexual abuse",
        "child molestation",
        "molested a minor",
        "molested a child",
        "indecent liberties with a minor",
        "indecent liberties with a child",
        "lewd act with a child",
        "lewd acts with a child",
        "lewd act upon a child",
        "sexual battery of a minor",
        "sexual battery of a child",
        "solicitation of a minor",
        "child pornography",
        "sexual exploitation of a minor",
        "sexual exploitation of a child",
        "criminal sexual conduct",
        "csc",
    }
)

# Used only in combination with _RELATIVE_IDENTIFICATION_PATTERN below
# -- catches "[Named person]'s minor child ..." paired with sexual-
# offense language elsewhere in the same text, even when none of
# SEXUAL_OFFENSE_MINOR_TERMS' specific phrases appear verbatim.
_SEXUAL_OFFENSE_CONTEXT_TERMS: frozenset[str] = frozenset(
    {
        "sexual",
        "sexually",
        "molest",
        "rape",
        "raped",
        "lewd",
        "indecent liberties",
        "csc",
        "criminal sexual conduct",
    }
)

# Indirect victim identification: a named person, possessive, then a
# minor-relative noun -- "Marlene Haywood's minor child", "Jane Doe's
# 14-year-old daughter". Matched against the ORIGINAL text (not
# lowercased) so the capitalized-name heuristic means something; the
# sexual-offense-context check right after is case-insensitive.
_RELATIVE_NOUNS = (
    r"(?:child|daughter|son|niece|nephew|granddaughter|grandson|"
    r"stepdaughter|stepson|ward)"
)
_RELATIVE_IDENTIFICATION_PATTERN = re.compile(
    r"\b[A-Z][a-zA-Z'-]+(?:\s[A-Z][a-zA-Z'-]+){0,2}'s\s+"
    r"(?:minor\s+|underage\s+|\d{1,2}-year-old\s+)?" + _RELATIVE_NOUNS + r"\b"
)


@dataclass(frozen=True)
class ContentSafetyMatch:
    reason: str
    matched_term: str


def check_text(text: object) -> ContentSafetyMatch | None:
    """Returns a match if `text` should be rejected, None if it's
    clear. Fail-closed: anything this function cannot evaluate as a
    real, non-empty string is itself a match, never a pass."""
    if not isinstance(text, str) or not text.strip():
        return ContentSafetyMatch(
            reason="cannot evaluate: input was not a non-empty string",
            matched_term="<fail-closed>",
        )

    lowered = text.lower()

    for term in SEXUAL_OFFENSE_MINOR_TERMS:
        if term in lowered:
            return ContentSafetyMatch(
                reason=f"sexual offense involving a minor: matched term {term!r}",
                matched_term=term,
            )

    if _RELATIVE_IDENTIFICATION_PATTERN.search(text):
        for term in _SEXUAL_OFFENSE_CONTEXT_TERMS:
            if term in lowered:
                return ContentSafetyMatch(
                    reason=(
                        "victim identified indirectly via a named relative in a "
                        f"sexual-offense context: matched term {term!r}"
                    ),
                    matched_term=term,
                )

    return None


def log_rejection(
    *, subject_id: int, source_label: str, statement: str, match: ContentSafetyMatch
) -> None:
    """The one place a rejection gets logged, so every call site
    produces the same shape -- source and matched reason, per the task
    this was built under. WARNING level, not ERROR: a rejection is
    the filter doing its job, not a failure (see
    packages/research/claim_extraction.py -- ingestion continues)."""
    logger.warning(
        "content safety rejection: subject_id=%s source=%s reason=%s statement=%r",
        subject_id,
        source_label,
        match.reason,
        statement[:200],
    )


class ClaimContentRejectedError(Exception):
    """Raised by packages.db.listeners's Claim.before_insert when
    check_text() matches Claim.statement. Not caught anywhere in this
    module -- the caller's insert attempt fails, exactly like every
    other persistence-layer invariant in this schema (narratable
    sourcing, living-evidence, eligibility scoring)."""

    def __init__(self, match: ContentSafetyMatch) -> None:
        self.match = match
        super().__init__(f"claim rejected by content safety filter: {match.reason}")
