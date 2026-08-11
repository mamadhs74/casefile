"""Deterministic claim-to-card mapping: which card each claim becomes,
not what that card looks like -- rendering lives in cards.py, this
module never touches an Image.

SCOPE BOUNDARY, same posture as cards.py's own: pure functions only.
No database access (no `packages.db` import, no `Session`), no LLM
calls, no `Shot`/`Asset` write, no image rendering. `ClaimRecord` below
carries exactly the plain fields this module's rules need -- it is not
a `Claim` ORM row and never becomes one; whatever calls `plan_cards`
with real data is responsible for building `ClaimRecord`s from
wherever claims actually live, on the other side of this boundary.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from packages.visual.cards import (
    AttributionCardSpec,
    ChapterTitleSpec,
    StatementCardSpec,
    TimelineSpec,
)


@dataclass(frozen=True)
class ClaimRecord:
    """One claim's plain data, as much as this module's rules need and
    no more. `claim_type` and `section` are bare strings, not enum
    members -- same reasoning packages/script/composition_provider.py's
    own `ClaimForComposition` already documents for its own claim_type/
    confidence fields: this module stays free of any dependency on
    packages.domain, and the caller is the one place that already holds
    real enum values and is responsible for stringifying them."""

    claim_id: int
    statement: str
    claim_type: str  # "FACT" or "CONTEMPORANEOUS_REPORT"
    section: str | None  # None means untagged (Sequence, by convention)
    date_anchor: str | None
    source_label: str | None


@dataclass(frozen=True)
class PlannedCard:
    """One entry in the planned card sequence. `claim_id` is `None`
    only for a `chapter_title` card -- a chapter title names a section,
    not a claim, and isn't attributable to any single one."""

    kind: str  # "chapter_title" | "statement" | "attribution" | "timeline"
    claim_id: int | None
    spec: ChapterTitleSpec | StatementCardSpec | AttributionCardSpec | TimelineSpec


def _classify(claim: ClaimRecord) -> str:
    """Rules 2-4, in precedence order. Rule 1 (chapter titles) is a
    structural insertion between claims, not a per-claim classification
    -- handled separately in plan_cards, not here.

    Rule 2 first, deliberately: a CONTEMPORANEOUS_REPORT claim with both
    a date_anchor and a source_label in Sequence still becomes a
    timeline card, not an attribution card -- date position in the
    narrative outranks attribution once a claim is in Sequence's own
    territory. Attribution only wins in Ground/Resolution, or in
    Sequence when the claim has no date_anchor to place it with."""
    untagged_or_sequence = claim.section is None or claim.section.lower() == "sequence"
    if untagged_or_sequence and claim.date_anchor is not None:
        return "timeline"
    if claim.claim_type == "CONTEMPORANEOUS_REPORT" and claim.source_label is not None:
        return "attribution"
    return "statement"


def _chapter_title_card(section: str | None) -> PlannedCard:
    # None is a section value like any other, not an absence to special-
    # case away -- it just titles as "Sequence" rather than being
    # skipped. Any other section string is capitalized for display
    # ("ground" -> "Ground"), matching how docs/ARCHITECTURES.md itself
    # names the three sections (Ground, Sequence, Resolution).
    title = "Sequence" if section is None else section.capitalize()
    return PlannedCard(kind="chapter_title", claim_id=None, spec=ChapterTitleSpec(title=title))


def plan_cards(claims: Sequence[ClaimRecord]) -> list[PlannedCard]:
    """Preserves input order -- claims arrive already ordered by
    composition (chronological within Sequence, whatever order Ground/
    Resolution were composed in), and nothing here re-sorts them.
    Deterministic and pure: the same input always produces the same
    output, and nothing here reads any state outside its own argument.

    Two passes, not one, because timeline position (rank among timeline
    claims specifically, not among all claims) can't be known until
    every claim's kind has already been decided -- an attribution or
    statement claim between two timeline claims must not consume a
    rank."""
    kinds = [_classify(claim) for claim in claims]

    timeline_indices = [i for i, kind in enumerate(kinds) if kind == "timeline"]
    positions: dict[int, float] = {}
    timeline_count = len(timeline_indices)
    if timeline_count == 1:
        positions[timeline_indices[0]] = 0.5
    elif timeline_count > 1:
        for rank, index in enumerate(timeline_indices):
            positions[index] = rank / (timeline_count - 1)

    cards: list[PlannedCard] = []
    previous_section: str | None = None
    for i, claim in enumerate(claims):
        if i == 0 or claim.section != previous_section:
            cards.append(_chapter_title_card(claim.section))
        previous_section = claim.section

        kind = kinds[i]
        if kind == "timeline":
            # Guaranteed by _classify's own condition for this branch;
            # asserted, not silently trusted, so a future edit that
            # decouples the two doesn't fail confusingly inside
            # TimelineSpec's constructor instead.
            assert claim.date_anchor is not None
            cards.append(
                PlannedCard(
                    kind="timeline",
                    claim_id=claim.claim_id,
                    spec=TimelineSpec(
                        date_anchor=claim.date_anchor,
                        statement=claim.statement,
                        position=positions[i],
                    ),
                )
            )
        elif kind == "attribution":
            assert claim.source_label is not None
            cards.append(
                PlannedCard(
                    kind="attribution",
                    claim_id=claim.claim_id,
                    spec=AttributionCardSpec(
                        statement=claim.statement, source_label=claim.source_label
                    ),
                )
            )
        else:
            cards.append(
                PlannedCard(
                    kind="statement",
                    claim_id=claim.claim_id,
                    spec=StatementCardSpec(statement=claim.statement),
                )
            )

    return cards
