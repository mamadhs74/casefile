"""The `chronological` architecture's script generator -- docs/SOURCING.md's
"events in order, resolution at end." No LLM call: this concatenates each
claim's own `statement` in date order. Deliberately dumb, on purpose --
this proves the plumbing (narratable enforcement, ordering, claim-to-
subject validation) works before any prose-quality concern is in scope.

Input is exactly `docs/SOURCING.md`'s script-generation contract: claim
table + architecture. Not input: any Source text -- this module never
touches `Source` or `text_path` at all, only `Claim.statement`.

Every claim_id must already be narratable -- packages/db/listeners.py's
narratable invariant is what this module leans on to guarantee every
sentence it emits is Tier-A-sourced; this function doesn't re-check
sourcing itself, it just refuses to run on a claim that hasn't been
through that gate.
"""

from __future__ import annotations

from typing import Literal

from sqlmodel import Session

from packages.db.models import Claim

Architecture = Literal["chronological"]


class ClaimNotFoundError(Exception):
    def __init__(self, claim_id: int) -> None:
        self.claim_id = claim_id
        super().__init__(f"no claim with id={claim_id}")


class ClaimNotInSubjectError(Exception):
    def __init__(self, claim_id: int, subject_id: int) -> None:
        self.claim_id = claim_id
        self.subject_id = subject_id
        super().__init__(f"claim {claim_id} does not belong to subject {subject_id}")


class ClaimNotNarratableError(Exception):
    def __init__(self, claim_id: int) -> None:
        self.claim_id = claim_id
        super().__init__(f"claim {claim_id} is not narratable -- flip it by hand first")


def generate_script(
    session: Session,
    subject_id: int,
    architecture: Architecture,
    claim_ids: list[int],
) -> str:
    """Every claim_id must exist, belong to subject_id, and be narratable --
    raises on the first one that isn't, naming which. Ordering is by
    date_anchor ascending; claims with no date_anchor sort last (a real
    limitation, not hidden: this architecture can't place an undated claim
    in time, so it goes at the end rather than being silently dropped),
    with claim id as the tiebreak for determinism when two claims share a
    date_anchor or both lack one. Output is one claim's statement per line
    -- concatenation, not composition; the only "connective structure" is
    that each line ends with a period so it reads as a sentence.
    """
    claims: list[Claim] = []
    for claim_id in claim_ids:
        claim = session.get(Claim, claim_id)
        if claim is None:
            raise ClaimNotFoundError(claim_id)
        if claim.subject_id != subject_id:
            raise ClaimNotInSubjectError(claim_id, subject_id)
        if not claim.narratable:
            raise ClaimNotNarratableError(claim_id)
        claims.append(claim)

    ordered = sorted(
        claims,
        key=lambda c: (c.date_anchor is None, c.date_anchor or "", c.id),
    )

    lines = [_as_sentence(claim.statement) for claim in ordered]
    return "\n".join(lines)


def _as_sentence(statement: str) -> str:
    text = statement.strip()
    if not text.endswith((".", "!", "?")):
        text += "."
    return text
