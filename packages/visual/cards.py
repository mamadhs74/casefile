"""Deterministic card renderers: (spec, Palette) -> a 3840x2160 RGB
still frame. v1 of packages/visual -- pure image rendering, nothing
else.

SCOPE BOUNDARY, load-bearing, not a style note: this module does no
database access (no `packages.db` import, no `Session`), makes no LLM
calls, and reads no `Script`/`Shot`/`Asset` row. A renderer's `spec`
dataclass carries exactly the plain data one card needs (a title
string, a statement string, a source label, a date and a position) --
never a `Claim` or any other ORM object. Deciding *which* card a given
claim should become, and turning that decision into persisted `Shot`
rows, is the shot planner -- a later task, not this one. If a change
here ever seems to need a `Session`, that's this boundary being
crossed; stop and flag it rather than importing one.

FONTS: three real font files on disk, required, no fallback. Pillow's
own bitmap default font (silently substituted when `ImageFont.load_default()`
is used, or when a missing path is swallowed some other way) is never
used anywhere in this module -- a rendering pipeline meant to produce
reviewable, reproducible output should fail loudly on a missing font,
not quietly substitute a different one and render something nobody
asked for. `_require_font` below raises at import time, not at first
render call, so a missing font is a startup failure, not a surprise
mid-run.

3840x2160 output is deliberate, not a placeholder resolution: final
delivery is 1080p, so a 4K source frame gives `Shot.motion_params`
(Ken Burns zoom/pan) up to 2x zoom before exceeding source resolution
and visibly softening (docs/SCHEMA.md's Shot section). Do not change
it here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from packages.visual.palette import RGB, Palette

# --------------------------------------------------------------------
# Fonts -- required, no substitution. See module docstring.
# --------------------------------------------------------------------

_FONT_DISPLAY_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
_FONT_BODY_PATH = "/System/Library/Fonts/Supplemental/Georgia.ttf"
_FONT_QUOTE_PATH = "/System/Library/Fonts/Supplemental/Georgia Italic.ttf"


class MissingFontError(Exception):
    """Raised at import time if a required font file is not present.
    See module docstring for why no fallback exists to catch this
    instead."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"required font not found: {path}")


def _require_font(path: str) -> str:
    if not Path(path).is_file():
        raise MissingFontError(path)
    return path


FONT_DISPLAY = _require_font(_FONT_DISPLAY_PATH)
FONT_BODY = _require_font(_FONT_BODY_PATH)
FONT_QUOTE = _require_font(_FONT_QUOTE_PATH)

# --------------------------------------------------------------------
# Canvas geometry
# --------------------------------------------------------------------

CARD_WIDTH = 3840
CARD_HEIGHT = 2160

# 10% inset on all sides, per spec. Everything a renderer draws --
# text, rules, markers -- stays within this box; nothing here ever
# paints into the outer 10% margin.
SAFE_AREA_FRACTION = 0.10

Box = tuple[int, int, int, int]  # left, top, right, bottom

_SAFE_LEFT = round(CARD_WIDTH * SAFE_AREA_FRACTION)
_SAFE_TOP = round(CARD_HEIGHT * SAFE_AREA_FRACTION)
_SAFE_RIGHT = CARD_WIDTH - _SAFE_LEFT
_SAFE_BOTTOM = CARD_HEIGHT - _SAFE_TOP
SAFE_BOX: Box = (_SAFE_LEFT, _SAFE_TOP, _SAFE_RIGHT, _SAFE_BOTTOM)

# Extra margin subtracted from SAFE_BOX before any text-fit calculation
# (not from shapes like the timeline rule, which may legitimately span
# the full safe width). Ink extents and advance widths aren't always
# byte-identical at the sub-pixel level; this buffer is cheap insurance
# against that, not a correction for a known bug.
_TEXT_FIT_BUFFER_PX = 16

# --------------------------------------------------------------------
# Text fitting: wrap to width, shrink to fit height. Never clip, never
# overflow -- see TextDoesNotFitError.
# --------------------------------------------------------------------

MIN_FONT_SIZE = 28
_LINE_SPACING = 1.3


class TextDoesNotFitError(Exception):
    """Raised when text cannot be shrunk to fit its target box even at
    MIN_FONT_SIZE. Overflowing the safe area silently, or clipping
    text, are exactly the failure modes this module exists to prevent
    -- raising instead of doing either is the point, not a gap to close
    later."""

    def __init__(self, text: str, min_size: int) -> None:
        self.text = text
        self.min_size = min_size
        super().__init__(
            f"text does not fit even at the minimum font size ({min_size}px): {text!r}"
        )


def _inset_box(box: Box, px: int) -> Box:
    left, top, right, bottom = box
    return (left + px, top + px, right - px, bottom - px)


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> float:
    """Ink extent, not advance width -- the actual rendered pixel
    span, which is the number that matters for "does this overflow,"
    and is never smaller than the advance width for the fonts used
    here."""
    if not text:
        return 0.0
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: float
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    max_width: int,
    max_height: int,
    start_size: int,
    *,
    min_size: int = MIN_FONT_SIZE,
) -> tuple[list[str], ImageFont.FreeTypeFont, int]:
    """Wraps `text` to `max_width` at `start_size`; if the wrapped
    block's total height exceeds `max_height`, or any wrapped line is
    still wider than `max_width` (a single word longer than the whole
    line), shrinks the font by 2px and re-wraps, down to `min_size`.
    Returns (lines, font, line_height) for the first size that fits
    both dimensions. Raises TextDoesNotFitError if nothing down to
    min_size fits -- never returns something that would overflow."""
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(font_path, size)
        lines = _wrap_text(draw, text, font, max_width)
        ascent, descent = font.getmetrics()
        line_height = round((ascent + descent) * _LINE_SPACING)
        block_height = line_height * len(lines)
        widest_line = max(_text_width(draw, line, font) for line in lines)
        if widest_line <= max_width and block_height <= max_height:
            return lines, font, line_height
        size -= 2
    raise TextDoesNotFitError(text, min_size)


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    line_height: int,
    box: Box,
    color: RGB,
) -> None:
    """Draws `lines` centered on both axes within `box`. Caller must
    have already fit `lines`/`font` to `box`'s dimensions via
    `_fit_text` -- this function positions and draws only, it does not
    re-check that anything fits."""
    left, top, right, bottom = box
    box_width = right - left
    box_height = bottom - top
    block_height = line_height * len(lines)
    start_y = top + (box_height - block_height) // 2
    center_x = left + box_width // 2
    for i, line in enumerate(lines):
        line_center_y = start_y + line_height * i + line_height // 2
        draw.text((center_x, line_center_y), line, font=font, fill=color, anchor="mm")


def _new_canvas(palette: Palette) -> Image.Image:
    return Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), color=palette.background)


# --------------------------------------------------------------------
# render_chapter_title
# --------------------------------------------------------------------

_TITLE_START_SIZE = 240


@dataclass(frozen=True)
class ChapterTitleSpec:
    """A section name (Ground, Sequence, Resolution, ...), rendered
    large and centered. Plain data only -- not a Claim, not a
    Section enum member; the caller stringifies whatever it's naming
    before building this spec, keeping this module free of any
    dependency on packages.domain."""

    title: str


def render_chapter_title(spec: ChapterTitleSpec, palette: Palette) -> Image.Image:
    image = _new_canvas(palette)
    draw = ImageDraw.Draw(image)
    box = _inset_box(SAFE_BOX, _TEXT_FIT_BUFFER_PX)
    box_width = box[2] - box[0]
    box_height = box[3] - box[1]
    lines, font, line_height = _fit_text(
        draw, spec.title, FONT_DISPLAY, box_width, box_height, _TITLE_START_SIZE
    )
    _draw_text_block(draw, lines, font, line_height, box, palette.foreground)
    return image


# --------------------------------------------------------------------
# render_statement_card
# --------------------------------------------------------------------

_STATEMENT_START_SIZE = 130


@dataclass(frozen=True)
class StatementCardSpec:
    """A claim's statement, rendered as plain typography. For
    claim_type == FACT (the caller's decision, not this module's --
    see module docstring on the scope boundary)."""

    statement: str


def render_statement_card(spec: StatementCardSpec, palette: Palette) -> Image.Image:
    image = _new_canvas(palette)
    draw = ImageDraw.Draw(image)
    box = _inset_box(SAFE_BOX, _TEXT_FIT_BUFFER_PX)
    box_width = box[2] - box[0]
    box_height = box[3] - box[1]
    lines, font, line_height = _fit_text(
        draw, spec.statement, FONT_BODY, box_width, box_height, _STATEMENT_START_SIZE
    )
    _draw_text_block(draw, lines, font, line_height, box, palette.foreground)
    return image


# --------------------------------------------------------------------
# render_attribution_card
# --------------------------------------------------------------------

_ATTRIBUTION_QUOTE_START_SIZE = 120
_ATTRIBUTION_SOURCE_START_SIZE = 70
_ATTRIBUTION_QUOTE_HEIGHT_FRACTION = 0.68
_ATTRIBUTION_GAP_FRACTION = 0.05


@dataclass(frozen=True)
class AttributionCardSpec:
    """A claim's statement (quoted, attributed) plus who it's
    attributed to. For claim_type == CONTEMPORANEOUS_REPORT -- the
    caller's decision, not this module's."""

    statement: str
    source_label: str


def render_attribution_card(spec: AttributionCardSpec, palette: Palette) -> Image.Image:
    image = _new_canvas(palette)
    draw = ImageDraw.Draw(image)
    box = _inset_box(SAFE_BOX, _TEXT_FIT_BUFFER_PX)
    left, top, right, bottom = box
    box_width = right - left
    box_height = bottom - top

    gap = round(box_height * _ATTRIBUTION_GAP_FRACTION)
    quote_budget_height = round(box_height * _ATTRIBUTION_QUOTE_HEIGHT_FRACTION)

    quote_lines, quote_font, quote_line_height = _fit_text(
        draw, spec.statement, FONT_QUOTE, box_width, quote_budget_height,
        _ATTRIBUTION_QUOTE_START_SIZE,
    )
    quote_height = quote_line_height * len(quote_lines)

    source_text = f"— {spec.source_label}"  # em dash, standard attribution style
    source_budget_height = box_height - quote_height - gap
    source_lines, source_font, source_line_height = _fit_text(
        draw, source_text, FONT_DISPLAY, box_width, source_budget_height,
        _ATTRIBUTION_SOURCE_START_SIZE,
    )
    source_height = source_line_height * len(source_lines)

    total_height = quote_height + gap + source_height
    block_top = top + (box_height - total_height) // 2

    quote_box: Box = (left, block_top, right, block_top + quote_height)
    _draw_text_block(
        draw, quote_lines, quote_font, quote_line_height, quote_box, palette.foreground
    )

    source_top = block_top + quote_height + gap
    source_box: Box = (left, source_top, right, source_top + source_height)
    _draw_text_block(draw, source_lines, source_font, source_line_height, source_box, palette.muted)

    return image


# --------------------------------------------------------------------
# render_timeline
# --------------------------------------------------------------------

_TIMELINE_DATE_START_SIZE = 90
_TIMELINE_STATEMENT_START_SIZE = 100
_TIMELINE_RULE_FRACTION = 0.55  # rule sits 55% down the safe box
_TIMELINE_RULE_WIDTH_PX = 6
_TIMELINE_MARKER_RADIUS_PX = 26
_TIMELINE_LABEL_GAP_PX = 36


@dataclass(frozen=True)
class TimelineSpec:
    """One point on a horizontal timeline. `position` is where along
    the rule the marker sits, 0.0 (left edge of the safe area) to 1.0
    (right edge) -- the caller computes this from date_anchor against
    whatever range the episode's timeline spans; this module has no
    date-parsing or date-comparison logic of its own."""

    date_anchor: str
    statement: str
    position: float


def render_timeline(spec: TimelineSpec, palette: Palette) -> Image.Image:
    image = _new_canvas(palette)
    draw = ImageDraw.Draw(image)
    box = _inset_box(SAFE_BOX, _TEXT_FIT_BUFFER_PX)
    left, top, right, bottom = box
    box_width = right - left
    box_height = bottom - top

    position = min(1.0, max(0.0, spec.position))
    rule_y = top + round(box_height * _TIMELINE_RULE_FRACTION)
    r = _TIMELINE_MARKER_RADIUS_PX
    # The rule itself spans the full box width, but the marker's own
    # circle extends r px past its center in every direction -- placing
    # its center at the raw box edge (position 0.0 or 1.0) would push
    # the circle itself past the safe area. Insetting the range marker_x
    # is chosen from by r on each side keeps the whole circle, not just
    # its center, inside the box at every position value.
    marker_x = left + r + round((box_width - 2 * r) * position)

    draw.line([(left, rule_y), (right, rule_y)], fill=palette.rule, width=_TIMELINE_RULE_WIDTH_PX)
    draw.ellipse([marker_x - r, rule_y - r, marker_x + r, rule_y + r], fill=palette.accent)

    # Date label, above the rule and marker, horizontally clamped so it
    # never overflows the safe box even when the marker sits at (or
    # near) position 0.0 or 1.0.
    date_max_height = max(rule_y - _TIMELINE_LABEL_GAP_PX - top, MIN_FONT_SIZE)
    date_lines, date_font, date_line_height = _fit_text(
        draw, spec.date_anchor, FONT_DISPLAY, box_width, date_max_height,
        _TIMELINE_DATE_START_SIZE,
    )
    date_height = date_line_height * len(date_lines)
    date_width = max(_text_width(draw, line, date_font) for line in date_lines)
    date_left = marker_x - date_width / 2
    date_left = min(max(date_left, left), right - date_width)
    date_top = rule_y - _TIMELINE_LABEL_GAP_PX - date_height
    date_box: Box = (
        round(date_left), date_top, round(date_left + date_width), date_top + date_height
    )
    _draw_text_block(draw, date_lines, date_font, date_line_height, date_box, palette.foreground)

    # Statement, below the rule and marker.
    statement_top = rule_y + r + _TIMELINE_LABEL_GAP_PX
    statement_box: Box = (left, statement_top, right, bottom)
    statement_lines, statement_font, statement_line_height = _fit_text(
        draw, spec.statement, FONT_BODY, box_width, bottom - statement_top,
        _TIMELINE_STATEMENT_START_SIZE,
    )
    _draw_text_block(
        draw, statement_lines, statement_font, statement_line_height,
        statement_box, palette.foreground,
    )

    return image
