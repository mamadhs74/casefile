"""Fitness assessment per docs/ARCHIVE-SPEC.md: resolution, aspect ratio, format."""

from __future__ import annotations

import pytest

from packages.archive.fitness import (
    BASE_LONG_EDGE_PX,
    FULL_MOTION_LONG_EDGE_PX,
    LETTERBOX_ONLY_WIDTH_PX,
    assess_fitness,
)
from packages.domain.enums import MotionType

# ---------------------------------------------------------------------------
# Resolution tiers
# ---------------------------------------------------------------------------


def test_1600px_image_forbids_zoom_motion() -> None:
    """The exact case named in docs/ARCHIVE-SPEC.md's test list."""
    report = assess_fitness(1600, 1000, "image/jpeg")
    assert report.meets_minimum_resolution is False
    assert MotionType.ZOOM_IN not in report.allowed_motion_types
    assert report.allowed_motion_types == frozenset()


def test_3000px_image_permits_zoom_motion() -> None:
    """The exact case named in docs/ARCHIVE-SPEC.md's test list."""
    report = assess_fitness(3000, 2000, "image/jpeg")
    assert report.meets_minimum_resolution is True
    assert MotionType.ZOOM_IN in report.allowed_motion_types
    assert report.allowed_motion_types == frozenset(MotionType)


def test_below_1920_rejects_every_motion_type_not_just_zoom() -> None:
    report = assess_fitness(1900, 1000, "image/jpeg")
    assert report.allowed_motion_types == frozenset()
    assert any("1920" in note for note in report.notes)


def test_at_exactly_1920_is_not_rejected() -> None:
    report = assess_fitness(1920, 1080, "image/jpeg")
    assert report.meets_minimum_resolution is True
    assert report.allowed_motion_types == frozenset({MotionType.STATIC, MotionType.DRIFT})


@pytest.mark.parametrize("long_edge", [1920, 2000, 2495])
def test_between_1920_and_full_motion_threshold_restricts_to_static_and_drift(
    long_edge: int,
) -> None:
    report = assess_fitness(long_edge, 1000, "image/jpeg")
    assert report.allowed_motion_types == frozenset({MotionType.STATIC, MotionType.DRIFT})
    assert MotionType.ZOOM_IN not in report.allowed_motion_types
    assert MotionType.ZOOM_OUT not in report.allowed_motion_types
    assert MotionType.PAN_LEFT not in report.allowed_motion_types
    assert MotionType.PAN_RIGHT not in report.allowed_motion_types
    assert MotionType.PUSH_IN_SLOW not in report.allowed_motion_types


def test_full_motion_threshold_matches_documented_1_3x_push() -> None:
    assert FULL_MOTION_LONG_EDGE_PX == pytest.approx(1920 * 1.3)
    assert BASE_LONG_EDGE_PX == 1920


def test_at_exactly_full_motion_threshold_permits_everything() -> None:
    long_edge = int(FULL_MOTION_LONG_EDGE_PX)
    report = assess_fitness(long_edge, 1000, "image/jpeg")
    assert report.allowed_motion_types == frozenset(MotionType)


# ---------------------------------------------------------------------------
# Aspect ratio and letterboxing
# ---------------------------------------------------------------------------


def test_aspect_ratio_is_width_over_height() -> None:
    report = assess_fitness(1920, 1080, "image/jpeg")
    assert report.aspect_ratio == pytest.approx(1920 / 1080)


def test_narrow_portrait_requires_letterbox() -> None:
    report = assess_fitness(800, 1200, "image/jpeg")
    assert report.requires_letterbox is True
    assert any("letterboxed" in note for note in report.notes)


def test_wide_enough_portrait_does_not_require_letterbox() -> None:
    report = assess_fitness(LETTERBOX_ONLY_WIDTH_PX, 1600, "image/jpeg")
    assert report.requires_letterbox is False


def test_landscape_never_requires_letterbox_even_if_narrow() -> None:
    """requires_letterbox is specifically about portrait orientation."""
    report = assess_fitness(900, 700, "image/jpeg")
    assert report.requires_letterbox is False


def test_square_image_does_not_require_letterbox() -> None:
    report = assess_fitness(500, 500, "image/jpeg")
    assert report.requires_letterbox is False


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mime_type",
    [
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/tiff",
        "image/bmp",
        "video/mp4",
        "video/webm",
    ],
)
def test_known_safe_formats_are_ok(mime_type: str) -> None:
    report = assess_fitness(1920, 1080, mime_type)
    assert report.format_ok is True


@pytest.mark.parametrize(
    "mime_type",
    [
        "image/svg+xml",
        "image/heic",
        "image/x-raw",
        "application/pdf",
        "image/avif",
    ],
)
def test_unrecognized_formats_reject(mime_type: str) -> None:
    report = assess_fitness(1920, 1080, mime_type)
    assert report.format_ok is False
    assert any(mime_type in note for note in report.notes)


def test_gif_is_format_ok_but_flagged_as_animated() -> None:
    report = assess_fitness(1920, 1080, "image/gif")
    assert report.format_ok is True
    assert report.is_animated_gif is True
    assert any("gif" in note.lower() for note in report.notes)


def test_non_gif_is_not_flagged_as_animated() -> None:
    report = assess_fitness(1920, 1080, "image/jpeg")
    assert report.is_animated_gif is False


# ---------------------------------------------------------------------------
# Degenerate input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width, height", [(0, 1000), (1000, 0), (-1, 1000), (1000, -1)])
def test_invalid_dimensions_reject_without_crashing(width: int, height: int) -> None:
    report = assess_fitness(width, height, "image/jpeg")
    assert report.meets_minimum_resolution is False
    assert report.allowed_motion_types == frozenset()
    assert report.long_edge_px == 0
    assert any("invalid dimensions" in note for note in report.notes)
