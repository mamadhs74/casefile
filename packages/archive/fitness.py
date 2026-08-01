"""Ken Burns fitness assessment per docs/ARCHIVE-SPEC.md.

A candidate that passes the license gate can still be unusable: too small to
push in on without visible softening, the wrong shape for a 16:9 frame, or a
format ffmpeg can't decode without extra work.

Unlike licensing, fitness is advisory, not a hard gate -- the operator may
still select a soft image for a shot where nothing better exists. This
module's job is to compute the signals, not decide for them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.domain.enums import MotionType

# For 1080p output, a static shot needs the full 1920px long edge just to
# fill the frame without upscaling. A zoom push needs that same 1920px
# *after* the push, so the source must be 1920 * max_zoom_factor going in.
# 1.3x is the reference push used throughout docs/ARCHIVE-SPEC.md ("at a
# 1.3x push that's roughly 2500px").
BASE_LONG_EDGE_PX = 1920
MAX_ZOOM_FACTOR = 1.3
FULL_MOTION_LONG_EDGE_PX = BASE_LONG_EDGE_PX * MAX_ZOOM_FACTOR

# Portrait stills narrower than a 1080p frame's height can't be panned or
# zoomed into usefully -- letterboxing against a flat card is the only
# treatment that doesn't upscale.
LETTERBOX_ONLY_WIDTH_PX = 1080

_RESTRICTED_MOTION_TYPES = frozenset({MotionType.STATIC, MotionType.DRIFT})
_ALL_MOTION_TYPES = frozenset(MotionType)

# ffmpeg decodes these without extra libraries. Everything else -- SVG
# (vector, needs rasterizing), HEIC/HEIF (needs libheif, often absent from
# stock builds), RAW camera formats, PDF -- is a reject, not an assumption
# of compatibility. Same philosophy as licensing.py: an unrecognized format
# doesn't get the benefit of the doubt.
_SAFE_IMAGE_MIME_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/tiff",
        "image/bmp",
    }
)

_SAFE_VIDEO_MIME_TYPES = frozenset(
    {
        "video/mp4",
        "video/webm",
        "video/quicktime",
        "video/mpeg",
        "video/x-msvideo",
    }
)

# GIF is natively decodable -- it isn't a format reject -- but it's flagged
# separately because it's almost never what you want in a documentary, and
# because we have no frame count here to tell a static GIF from an animated
# one. Every GIF is flagged; that's the conservative direction to be wrong in.
_GIF_MIME_TYPE = "image/gif"

_KNOWN_MIME_TYPES = _SAFE_IMAGE_MIME_TYPES | _SAFE_VIDEO_MIME_TYPES | {_GIF_MIME_TYPE}


@dataclass(frozen=True)
class FitnessReport:
    long_edge_px: int
    aspect_ratio: float
    meets_minimum_resolution: bool
    allowed_motion_types: frozenset[MotionType]
    requires_letterbox: bool
    format_ok: bool
    is_animated_gif: bool
    notes: list[str] = field(default_factory=list)


def assess_fitness(width: int, height: int, mime_type: str) -> FitnessReport:
    notes: list[str] = []

    if width <= 0 or height <= 0:
        notes.append(f"invalid dimensions ({width}x{height})")
        return FitnessReport(
            long_edge_px=0,
            aspect_ratio=0.0,
            meets_minimum_resolution=False,
            allowed_motion_types=frozenset(),
            requires_letterbox=False,
            format_ok=_format_ok(mime_type, notes),
            is_animated_gif=mime_type == _GIF_MIME_TYPE,
            notes=notes,
        )

    long_edge_px = max(width, height)
    aspect_ratio = width / height

    meets_minimum_resolution, allowed_motion_types = _resolution_tier(long_edge_px, notes)

    requires_letterbox = height > width and width < LETTERBOX_ONLY_WIDTH_PX
    if requires_letterbox:
        notes.append(
            f"portrait image narrower than {LETTERBOX_ONLY_WIDTH_PX}px is usable only letterboxed"
        )

    format_ok = _format_ok(mime_type, notes)
    is_animated_gif = mime_type == _GIF_MIME_TYPE
    if is_animated_gif:
        notes.append("image/gif may be animated -- verify before using as a still")

    return FitnessReport(
        long_edge_px=long_edge_px,
        aspect_ratio=aspect_ratio,
        meets_minimum_resolution=meets_minimum_resolution,
        allowed_motion_types=allowed_motion_types,
        requires_letterbox=requires_letterbox,
        format_ok=format_ok,
        is_animated_gif=is_animated_gif,
        notes=notes,
    )


def _resolution_tier(long_edge_px: int, notes: list[str]) -> tuple[bool, frozenset[MotionType]]:
    if long_edge_px < BASE_LONG_EDGE_PX:
        notes.append(
            f"{long_edge_px}px long edge is below the {BASE_LONG_EDGE_PX}px minimum -- "
            "no motion type is safe without upscaling"
        )
        return False, frozenset()

    if long_edge_px < FULL_MOTION_LONG_EDGE_PX:
        notes.append(
            f"{long_edge_px}px long edge supports only static and drift motion -- below the "
            f"{FULL_MOTION_LONG_EDGE_PX:.0f}px needed for a {MAX_ZOOM_FACTOR}x zoom push"
        )
        return True, _RESTRICTED_MOTION_TYPES

    return True, _ALL_MOTION_TYPES


def _format_ok(mime_type: str, notes: list[str]) -> bool:
    ok = mime_type in _KNOWN_MIME_TYPES
    if not ok:
        notes.append(f"{mime_type!r} is not a format ffmpeg decodes without extra work")
    return ok
