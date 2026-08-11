"""packages/visual/timing.py -- card durations from word counts. Pure-
function tests: no database, no audio, no fixtures."""

from __future__ import annotations

from packages.visual.cards import ChapterTitleSpec, StatementCardSpec
from packages.visual.planner import PlannedCard
from packages.visual.timing import (
    CHAPTER_TITLE_SECONDS,
    MAX_CARD_SECONDS,
    MIN_CARD_SECONDS,
    NARRATION_WPM,
    assign_durations,
    duration_for_words,
    total_runtime,
)


def _words(n: int) -> str:
    return " ".join(["word"] * n)


def _statement_card(claim_id: int, word_count: int) -> PlannedCard:
    return PlannedCard(
        kind="statement",
        claim_id=claim_id,
        spec=StatementCardSpec(statement=_words(word_count)),
    )


def _chapter_title_card() -> PlannedCard:
    return PlannedCard(kind="chapter_title", claim_id=None, spec=ChapterTitleSpec(title="Sequence"))


def test_30_word_card_at_150_wpm_is_12_seconds() -> None:
    assert duration_for_words(30, wpm=NARRATION_WPM) == 12.0


def test_both_clamps_fire_on_pathological_input() -> None:
    durations = assign_durations([_statement_card(1, 1), _statement_card(2, 500)])
    assert durations[0] == MIN_CARD_SECONDS
    assert durations[1] == MAX_CARD_SECONDS


def test_chapter_titles_are_exactly_2_5_seconds() -> None:
    durations = assign_durations([_chapter_title_card(), _chapter_title_card()])
    assert durations == [CHAPTER_TITLE_SECONDS, CHAPTER_TITLE_SECONDS]


def test_neither_clamp_fires_in_the_8_to_31_word_range() -> None:
    for n in range(8, 32):
        durations = assign_durations([_statement_card(1, n)])
        assert MIN_CARD_SECONDS < durations[0] < MAX_CARD_SECONDS, n


def test_total_runtime_sums_correctly() -> None:
    assert total_runtime([1.111, 2.222, 3.333]) == 6.666


def test_assign_durations_returns_one_value_per_card() -> None:
    cards = [
        _chapter_title_card(),
        _statement_card(1, 10),
        _statement_card(2, 20),
    ]
    durations = assign_durations(cards)
    assert len(durations) == len(cards)
