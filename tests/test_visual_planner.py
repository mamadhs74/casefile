"""packages/visual/planner.py -- deterministic claim-to-card mapping.
Pure-function tests: no database, no fixtures, no Session -- plan_cards
takes and returns plain dataclasses, so a test is just building a list
of ClaimRecord and reading back the PlannedCard list.
"""

from __future__ import annotations

from packages.visual.cards import (
    AttributionCardSpec,
    ChapterTitleSpec,
    StatementCardSpec,
    TimelineSpec,
)
from packages.visual.planner import ClaimRecord, plan_cards


def _claim(
    claim_id: int,
    *,
    statement: str = "A statement.",
    claim_type: str = "FACT",
    section: str | None = None,
    date_anchor: str | None = None,
    source_label: str | None = None,
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=claim_id,
        statement=statement,
        claim_type=claim_type,
        section=section,
        date_anchor=date_anchor,
        source_label=source_label,
    )


def test_fact_with_no_date_anchor_in_ground_is_statement_card() -> None:
    claims = [_claim(1, claim_type="FACT", section="ground", date_anchor=None)]
    cards = plan_cards(claims)

    claim_cards = [c for c in cards if c.kind != "chapter_title"]
    assert len(claim_cards) == 1
    card = claim_cards[0]
    assert card.kind == "statement"
    assert card.claim_id == 1
    assert isinstance(card.spec, StatementCardSpec)
    assert card.spec.statement == "A statement."


def test_contemporaneous_report_with_source_label_in_ground_is_attribution_card() -> None:
    claims = [
        _claim(
            1,
            claim_type="CONTEMPORANEOUS_REPORT",
            section="ground",
            source_label="Boston Globe",
        )
    ]
    cards = plan_cards(claims)

    claim_cards = [c for c in cards if c.kind != "chapter_title"]
    assert len(claim_cards) == 1
    card = claim_cards[0]
    assert card.kind == "attribution"
    assert isinstance(card.spec, AttributionCardSpec)
    assert card.spec.source_label == "Boston Globe"


def test_contemporaneous_report_with_date_anchor_in_sequence_is_timeline_not_attribution() -> None:
    """Rule 2 beats rule 3: a claim eligible for both timeline and
    attribution treatment gets timeline."""
    claims = [
        _claim(
            1,
            claim_type="CONTEMPORANEOUS_REPORT",
            section="sequence",
            date_anchor="1893-06-20",
            source_label="Boston Globe",
        )
    ]
    cards = plan_cards(claims)

    claim_cards = [c for c in cards if c.kind != "chapter_title"]
    assert len(claim_cards) == 1
    card = claim_cards[0]
    assert card.kind == "timeline"
    assert isinstance(card.spec, TimelineSpec)


def test_contemporaneous_report_with_no_source_label_is_statement_card() -> None:
    claims = [
        _claim(1, claim_type="CONTEMPORANEOUS_REPORT", section="ground", source_label=None)
    ]
    cards = plan_cards(claims)

    claim_cards = [c for c in cards if c.kind != "chapter_title"]
    assert len(claim_cards) == 1
    assert claim_cards[0].kind == "statement"


def test_chapter_title_emitted_at_start_and_once_per_section_change() -> None:
    claims = [
        _claim(1, section="ground"),
        _claim(2, section="ground"),
        _claim(3, section=None),  # untagged -> Sequence
        _claim(4, section=None),
        _claim(5, section="resolution"),
    ]
    cards = plan_cards(claims)

    assert cards[0].kind == "chapter_title"

    chapter_titles = [c for c in cards if c.kind == "chapter_title"]
    assert len(chapter_titles) == 3
    titles = [c.spec.title for c in chapter_titles if isinstance(c.spec, ChapterTitleSpec)]
    assert titles == ["Ground", "Sequence", "Resolution"]


def test_consecutive_claims_same_section_produce_no_repeated_chapter_title() -> None:
    claims = [
        _claim(1, section="ground"),
        _claim(2, section="ground"),
        _claim(3, section="ground"),
    ]
    cards = plan_cards(claims)

    chapter_titles = [c for c in cards if c.kind == "chapter_title"]
    assert len(chapter_titles) == 1


def test_timeline_positions_span_0_to_1_and_strictly_increase() -> None:
    claims = [
        _claim(i, section="sequence", date_anchor=f"1893-06-{10 + i:02d}") for i in range(5)
    ]
    cards = plan_cards(claims)

    timeline_cards = [c for c in cards if c.kind == "timeline"]
    assert len(timeline_cards) == 5
    positions = [c.spec.position for c in timeline_cards if isinstance(c.spec, TimelineSpec)]

    assert all(0.0 <= p <= 1.0 for p in positions)
    assert positions == sorted(positions)
    assert len(set(positions)) == len(positions)  # strictly increasing, not merely non-decreasing
    assert positions[0] == 0.0
    assert positions[-1] == 1.0


def test_lone_timeline_claim_gets_position_one_half() -> None:
    claims = [_claim(1, section="sequence", date_anchor="1893-06-20")]
    cards = plan_cards(claims)

    timeline_cards = [c for c in cards if c.kind == "timeline"]
    assert len(timeline_cards) == 1
    spec = timeline_cards[0].spec
    assert isinstance(spec, TimelineSpec)
    assert spec.position == 0.5


def test_plan_cards_is_deterministic_across_repeated_calls() -> None:
    claims = [
        _claim(1, claim_type="FACT", section="ground"),
        _claim(2, claim_type="CONTEMPORANEOUS_REPORT", section="ground", source_label="A Paper"),
        _claim(3, section="sequence", date_anchor="1893-06-01"),
        _claim(4, section="sequence", date_anchor="1893-06-20"),
        _claim(5, section="resolution"),
    ]

    first = plan_cards(claims)
    second = plan_cards(claims)

    assert first == second
