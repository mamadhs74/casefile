"""packages/visual/cards.py, packages/visual/palette.py -- smoke tests,
not pixel tests, per CLAUDE.md ("rendering gets smoke tests, not pixel
tests"): each renderer runs against real fonts and produces real output
of the right shape, nothing here compares against a golden image.

The one place these tests do look at actual pixels is the safe-area
overflow check -- not a pixel-perfect comparison, just "is every
non-background pixel inside the 10% inset box," which is a real
correctness property (a card that bleeds outside its safe area will
crop or overlap when composited later), checked via
ImageChops.difference(...).getbbox() rather than a per-pixel loop.
"""

from __future__ import annotations

from PIL import Image, ImageChops

from packages.visual.cards import (
    CARD_HEIGHT,
    CARD_WIDTH,
    SAFE_BOX,
    AttributionCardSpec,
    ChapterTitleSpec,
    StatementCardSpec,
    TimelineSpec,
    render_attribution_card,
    render_chapter_title,
    render_statement_card,
    render_timeline,
)
from packages.visual.palette import Palette, palette_for

_LONG_STATEMENT = (
    "Bridget Sullivan testified that she heard no quarrels in the household "
    "that morning, and that she had been washing windows outside when the "
    "alarm was raised by Lizzie Borden from inside the house on August 4th."
)
assert len(_LONG_STATEMENT) >= 200  # the fixture this module's own spec asks for

_PALETTE = palette_for("chronological", episode_id=1)


def _render_one_of_each(palette: Palette) -> dict[str, Image.Image]:
    """One call per renderer, each typed against its own function
    signature -- deliberately not a list of (renderer, spec) pairs:
    the four renderers take four different spec types, so a homogeneous
    list would need either a common spec supertype that doesn't exist
    or a loosely-typed callable that mypy --strict correctly refuses to
    call ("cannot call function of unknown type"). Naming each call
    directly is more typing, not less type safety."""
    return {
        "chapter_title": render_chapter_title(ChapterTitleSpec(title="Sequence"), palette),
        "statement_card": render_statement_card(
            StatementCardSpec(statement="The jury convicted Reyes of grand larceny."), palette
        ),
        "attribution_card": render_attribution_card(
            AttributionCardSpec(
                statement="Reyes was seen carrying a canvas satchel after hours.",
                source_label="Boston Globe, June 20 1893",
            ),
            palette,
        ),
        "timeline": render_timeline(
            TimelineSpec(date_anchor="1893-06-20", statement="The verdict was read.", position=0.5),
            palette,
        ),
    }


def _content_bbox(
    image: Image.Image, background: tuple[int, int, int]
) -> tuple[int, int, int, int] | None:
    """Bounding box of every non-background pixel, or None if the image
    is blank. Fast (no Python-level pixel loop) via PIL's own diff."""
    bg_image = Image.new("RGB", image.size, color=background)
    return ImageChops.difference(image, bg_image).getbbox()


def test_render_functions_return_exact_card_dimensions() -> None:
    for name, image in _render_one_of_each(_PALETTE).items():
        assert image.size == (CARD_WIDTH, CARD_HEIGHT), name
        assert image.mode == "RGB", name


def test_render_functions_produce_non_blank_output() -> None:
    for name, image in _render_one_of_each(_PALETTE).items():
        bbox = _content_bbox(image, _PALETTE.background)
        assert bbox is not None, f"{name} produced no non-background pixels"


def test_long_statement_stays_inside_safe_area_on_statement_card() -> None:
    spec = StatementCardSpec(statement=_LONG_STATEMENT)
    image = render_statement_card(spec, _PALETTE)

    bbox = _content_bbox(image, _PALETTE.background)
    assert bbox is not None

    left, top, right, bottom = bbox
    safe_left, safe_top, safe_right, safe_bottom = SAFE_BOX
    assert left >= safe_left
    assert top >= safe_top
    assert right <= safe_right
    assert bottom <= safe_bottom


def test_long_statement_stays_inside_safe_area_on_attribution_card() -> None:
    spec = AttributionCardSpec(statement=_LONG_STATEMENT, source_label="A Period Newspaper")
    image = render_attribution_card(spec, _PALETTE)

    bbox = _content_bbox(image, _PALETTE.background)
    assert bbox is not None

    left, top, right, bottom = bbox
    safe_left, safe_top, safe_right, safe_bottom = SAFE_BOX
    assert left >= safe_left
    assert top >= safe_top
    assert right <= safe_right
    assert bottom <= safe_bottom


def test_timeline_marker_stays_inside_safe_area_at_extreme_positions() -> None:
    """position=0.0 and position=1.0 are the case that actually caught a
    real bug during development: the marker circle's radius extends past
    its own center, so placing the center exactly at the safe-area edge
    pushed the circle itself outside it. Covered explicitly, not just via
    the long-statement checks above, which never exercise the extremes."""
    safe_left, safe_top, safe_right, safe_bottom = SAFE_BOX
    for position in (0.0, 1.0):
        spec = TimelineSpec(date_anchor="1893-06-20", statement=_LONG_STATEMENT, position=position)
        image = render_timeline(spec, _PALETTE)

        bbox = _content_bbox(image, _PALETTE.background)
        assert bbox is not None

        left, top, right, bottom = bbox
        assert left >= safe_left, position
        assert top >= safe_top, position
        assert right <= safe_right, position
        assert bottom <= safe_bottom, position


def test_timeline_clamps_out_of_range_position() -> None:
    """position is documented as [0, 1]; out-of-range values must not
    push the marker outside the safe area either, since nothing upstream
    of this module currently validates the range before it arrives."""
    safe_left, safe_top, safe_right, safe_bottom = SAFE_BOX
    for position in (-5.0, 5.0):
        spec = TimelineSpec(date_anchor="1893-06-20", statement="short", position=position)
        image = render_timeline(spec, _PALETTE)

        bbox = _content_bbox(image, _PALETTE.background)
        assert bbox is not None

        left, top, right, bottom = bbox
        assert left >= safe_left, position
        assert top >= safe_top, position
        assert right <= safe_right, position
        assert bottom <= safe_bottom, position


def test_palette_for_is_deterministic_across_separate_calls() -> None:
    first = palette_for("chronological", episode_id=1)
    second = palette_for("chronological", episode_id=1)
    assert first == second

    # episode_id is documented as unread in v1 -- a different episode_id
    # for the same architecture must still yield the same palette.
    third = palette_for("chronological", episode_id=999)
    assert first == third


def test_palette_for_differs_across_architectures() -> None:
    chronological = palette_for("chronological", episode_id=1)
    record_forward = palette_for("record_forward", episode_id=1)
    assert chronological != record_forward


def test_palette_for_returns_hand_written_palette_shape() -> None:
    palette = palette_for("chronological", episode_id=1)
    assert isinstance(palette, Palette)
    for channel in (
        palette.background,
        palette.foreground,
        palette.accent,
        palette.muted,
        palette.rule,
    ):
        assert len(channel) == 3
        assert all(0 <= value <= 255 for value in channel)
