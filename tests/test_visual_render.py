"""packages/visual/render.py -- cards to video via ffmpeg. Smoke tests,
not pixel tests, per CLAUDE.md. Tests that actually shell out to ffmpeg
are marked slow -- pyproject.toml's addopts excludes them from the
default run (opt in with `pytest -m slow`); everything else here runs
in the default suite.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from packages.domain.enums import MotionType
from packages.visual.cards import ChapterTitleSpec, StatementCardSpec
from packages.visual.palette import palette_for
from packages.visual.planner import PlannedCard
from packages.visual.render import MismatchedLengthsError, render_cards

CardPlan = tuple[list[PlannedCard], list[float], list[tuple[MotionType, dict[str, float]]]]


def _statement_card(claim_id: int) -> PlannedCard:
    return PlannedCard(
        kind="statement",
        claim_id=claim_id,
        spec=StatementCardSpec(statement="A short statement."),
    )


def _chapter_title_card() -> PlannedCard:
    return PlannedCard(kind="chapter_title", claim_id=None, spec=ChapterTitleSpec(title="Ground"))


def _three_card_plan() -> CardPlan:
    cards = [_chapter_title_card(), _statement_card(1), _statement_card(2)]
    durations = [2.5, 1.5, 1.5]
    motions: list[tuple[MotionType, dict[str, float]]] = [
        (MotionType.STATIC, {}),
        (MotionType.ZOOM_IN, {"zoom_start": 1.0, "zoom_end": 1.15}),
        (MotionType.DRIFT, {"zoom_start": 1.04, "zoom_end": 1.04, "pan_x": 0.02}),
    ]
    return cards, durations, motions


def _ffprobe(path: Path, entries: str) -> str:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", entries,
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def test_mismatched_lengths_raise(tmp_path: Path) -> None:
    cards = [_statement_card(1), _statement_card(2)]
    durations = [1.5]
    motions: list[tuple[MotionType, dict[str, float]]] = [(MotionType.STATIC, {})]

    with pytest.raises(MismatchedLengthsError):
        render_cards(cards, palette_for("chronological", 1), durations, motions, tmp_path)


@pytest.mark.slow
def test_three_card_plan_produces_three_pngs(tmp_path: Path) -> None:
    cards, durations, motions = _three_card_plan()
    render_cards(cards, palette_for("chronological", 1), durations, motions, tmp_path)

    pngs = sorted(tmp_path.glob("card_*.png"))
    assert len(pngs) == 3


@pytest.mark.slow
def test_returned_path_exists_and_is_non_empty(tmp_path: Path) -> None:
    cards, durations, motions = _three_card_plan()
    out_path = render_cards(cards, palette_for("chronological", 1), durations, motions, tmp_path)

    assert out_path.exists()
    assert out_path.stat().st_size > 0


@pytest.mark.slow
def test_ffprobe_duration_matches_sum_of_durations(tmp_path: Path) -> None:
    cards, durations, motions = _three_card_plan()
    out_path = render_cards(cards, palette_for("chronological", 1), durations, motions, tmp_path)

    reported = float(_ffprobe(out_path, "format=duration"))
    expected = sum(durations)
    assert abs(reported - expected) <= 0.5


@pytest.mark.slow
def test_ffprobe_reports_1920x1080(tmp_path: Path) -> None:
    cards, durations, motions = _three_card_plan()
    out_path = render_cards(cards, palette_for("chronological", 1), durations, motions, tmp_path)

    assert _ffprobe(out_path, "stream=width") == "1920"
    assert _ffprobe(out_path, "stream=height") == "1080"
