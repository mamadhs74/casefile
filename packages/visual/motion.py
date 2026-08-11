"""Deterministic MotionType + motion_params assignment per card.

SCOPE BOUNDARY, same posture as the rest of packages/visual: pure
functions only. No database access, no LLM calls, no Shot/Asset write,
no image rendering, no ffmpeg. `assign_motion` returns plain
(MotionType, dict) tuples -- turning those into a persisted `Shot` row
is a later task's job, not this module's.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence

from packages.domain.enums import MotionType
from packages.visual.planner import PlannedCard

# Cards render at 3840x2160 (cards.py) against a 1080p delivery target
# -- MAX_ZOOM=2.0 is exactly the point past which a Ken Burns zoom
# starts sampling beyond source resolution and visibly softens
# (docs/SCHEMA.md's Shot section: "a zoom that exceeds the source
# resolution produces visible softening").
MAX_ZOOM = 2.0

# The rotation assign_motion steps through for every non-chapter-title
# card. PAN_LEFT/PAN_RIGHT exist on MotionType but are never assigned
# here -- this module's rotation is deliberately a fixed 4, not every
# member of the enum.
_ROTATION_MOTIONS: tuple[MotionType, ...] = (
    MotionType.ZOOM_IN,
    MotionType.ZOOM_OUT,
    MotionType.PUSH_IN_SLOW,
    MotionType.DRIFT,
)

_MOTION_PARAMS: dict[MotionType, dict[str, float]] = {
    MotionType.STATIC: {},
    MotionType.ZOOM_IN: {"zoom_start": 1.0, "zoom_end": 1.15},
    MotionType.ZOOM_OUT: {"zoom_start": 1.15, "zoom_end": 1.0},
    MotionType.PUSH_IN_SLOW: {"zoom_start": 1.0, "zoom_end": 1.06},
    MotionType.DRIFT: {"zoom_start": 1.04, "zoom_end": 1.04, "pan_x": 0.02},
}


class ZoomExceedsSourceError(Exception):
    """Raised when a motion_params dict's zoom_start or zoom_end
    exceeds MAX_ZOOM -- see this module's own MAX_ZOOM comment for why
    that bound exists."""

    def __init__(self, params: dict[str, float]) -> None:
        self.params = params
        super().__init__(f"motion params exceed MAX_ZOOM ({MAX_ZOOM}): {params!r}")


def validate_zoom_bounds(params: dict[str, float]) -> None:
    for key in ("zoom_start", "zoom_end"):
        value = params.get(key)
        if value is not None and value > MAX_ZOOM:
            raise ZoomExceedsSourceError(params)


def _rotation_for(architecture: str) -> list[MotionType]:
    """Deterministic: the same architecture string always yields the
    same rotation order, across processes and runs -- same approach as
    packages/visual/palette.py::palette_for, same reasoning for why
    hashlib.sha256 is used instead of builtin hash() (salted per
    process, would silently change the order every restart)."""
    digest = hashlib.sha256(architecture.encode("utf-8")).digest()
    seed = int.from_bytes(digest, "big")
    rng = random.Random(seed)
    return rng.sample(list(_ROTATION_MOTIONS), len(_ROTATION_MOTIONS))


def assign_motion(
    cards: Sequence[PlannedCard], architecture: str
) -> list[tuple[MotionType, dict[str, float]]]:
    """One (MotionType, motion_params) pair per card, same order as
    `cards`. Chapter titles are always STATIC with empty params -- they
    carry no image worth animating over, just section text. Every
    other card steps through `_rotation_for(architecture)` by its
    position in `cards` (not by a separate non-chapter-only counter):
    since the rotation has 4 entries and neither a skip of 1 (directly
    adjacent non-chapter cards) nor a skip of 2 (two non-chapter cards
    with one chapter title between them) is a multiple of 4, stepping
    by the full card index already guarantees no two adjacent
    non-chapter cards share a motion type, without needing a second
    counter.
    """
    rotation = _rotation_for(architecture)
    assigned: list[tuple[MotionType, dict[str, float]]] = []
    for i, card in enumerate(cards):
        motion = MotionType.STATIC if card.kind == "chapter_title" else rotation[i % len(rotation)]
        params = dict(_MOTION_PARAMS[motion])  # copy -- callers must not share one mutable dict
        validate_zoom_bounds(params)
        assigned.append((motion, params))
    return assigned
