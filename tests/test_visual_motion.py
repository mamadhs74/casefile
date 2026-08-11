"""packages/visual/motion.py -- deterministic MotionType + motion_params
assignment. Pure-function tests: no database, no ffmpeg, no rendering."""

from __future__ import annotations

import pytest

from packages.domain.enums import MotionType
from packages.visual.cards import ChapterTitleSpec, StatementCardSpec
from packages.visual.motion import (
    MAX_ZOOM,
    ZoomExceedsSourceError,
    assign_motion,
    validate_zoom_bounds,
)
from packages.visual.planner import PlannedCard


def _statement_card(claim_id: int) -> PlannedCard:
    return PlannedCard(
        kind="statement", claim_id=claim_id, spec=StatementCardSpec(statement="A statement.")
    )


def _chapter_title_card() -> PlannedCard:
    return PlannedCard(kind="chapter_title", claim_id=None, spec=ChapterTitleSpec(title="Ground"))


def _mixed_cards() -> list[PlannedCard]:
    # Two chapter titles, five statement cards, with one pair of
    # non-chapter cards directly adjacent to a chapter title (stmt3,
    # chapter, stmt4) -- exercises both adjacency shapes assign_motion's
    # own docstring reasons about (skip of 1, skip of 2).
    return [
        _chapter_title_card(),
        _statement_card(1),
        _statement_card(2),
        _statement_card(3),
        _chapter_title_card(),
        _statement_card(4),
        _statement_card(5),
    ]


def test_chapter_titles_are_always_static() -> None:
    cards = _mixed_cards()
    assigned = assign_motion(cards, "chronological")
    for card, (motion, params) in zip(cards, assigned, strict=True):
        if card.kind == "chapter_title":
            assert motion == MotionType.STATIC
            assert params == {}


def test_no_two_adjacent_non_chapter_cards_share_a_motion() -> None:
    cards = _mixed_cards()
    assigned = assign_motion(cards, "chronological")
    non_chapter_motions = [
        motion
        for card, (motion, _params) in zip(cards, assigned, strict=True)
        if card.kind != "chapter_title"
    ]
    # strict=False, deliberately: pairing a sequence against its own
    # tail is off-by-one by construction, not a length mismatch to
    # guard against.
    for earlier, later in zip(non_chapter_motions, non_chapter_motions[1:], strict=False):
        assert earlier != later


def test_same_architecture_gives_same_sequence_twice() -> None:
    cards = _mixed_cards()
    first = assign_motion(cards, "chronological")
    second = assign_motion(cards, "chronological")
    assert first == second


def test_different_architectures_give_different_sequences() -> None:
    cards = _mixed_cards()
    chronological = assign_motion(cards, "chronological")
    record_forward = assign_motion(cards, "record_forward")
    assert chronological != record_forward


def test_every_assigned_params_dict_passes_validate_zoom_bounds() -> None:
    cards = _mixed_cards()
    assigned = assign_motion(cards, "chronological")
    for _motion, params in assigned:
        validate_zoom_bounds(params)  # must not raise


def test_hand_built_params_over_max_zoom_raises() -> None:
    params = {"zoom_start": 1.0, "zoom_end": 2.5}
    assert 2.5 > MAX_ZOOM

    with pytest.raises(ZoomExceedsSourceError) as exc_info:
        validate_zoom_bounds(params)
    assert exc_info.value.params == params
