"""Deterministic per-architecture colour palettes for packages/visual's
card renderers (cards.py).

Palette is a property of the episode's narrative *architecture*
(`chronological`, `record_forward`, ...), not of the individual episode
-- two episodes sharing an architecture share a look on purpose, the
same way a documentary series' recurring segments share a visual
identity. `episode_id` is accepted by `palette_for` for a future
per-episode variation dimension (R2's structural-variation mandate may
eventually want one) but is unread in this v1: nothing about today's
card design varies per episode, only per architecture.

No database access here -- `architecture` is a plain string the caller
already has (e.g. `Episode.architecture.value`), not something this
module looks up itself. See cards.py's own module docstring for the
scope boundary this whole package stays inside.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Palette:
    """Five colours, each RGB (0-255 per channel). `rule` is separate
    from `muted` even though both are desaturated -- `rule` is for thin
    structural lines (timeline rules, dividers), `muted` is for
    secondary text (source labels) -- a renderer choosing between them
    is choosing "a line" vs. "text that reads at a glance as less
    important," not picking two names for the same colour."""

    background: RGB
    foreground: RGB
    accent: RGB
    muted: RGB
    rule: RGB


# Dark base, saturated accent -- CLAUDE.md's frontend convention,
# applied here because these cards are the same viewer-facing surface
# the frontend convention describes, not a UI screen but the same
# visual language. Hand-written, not generated or sampled from a
# continuous space -- deterministic selection (below) needs a fixed,
# finite list to select *from*, and a hand-picked list is also the only
# way to guarantee every palette actually reads as "dark base, one
# saturated accent" rather than whatever a formula happens to produce.
# At least four required; this is exactly four.
_PALETTES: tuple[Palette, ...] = (
    Palette(
        background=(18, 18, 24),
        foreground=(235, 235, 240),
        accent=(214, 69, 65),  # saturated red
        muted=(120, 120, 130),
        rule=(70, 70, 80),
    ),
    Palette(
        background=(16, 24, 22),
        foreground=(230, 238, 234),
        accent=(56, 176, 130),  # saturated green
        muted=(110, 128, 120),
        rule=(60, 78, 70),
    ),
    Palette(
        background=(20, 20, 30),
        foreground=(232, 232, 242),
        accent=(90, 120, 235),  # saturated blue
        muted=(115, 115, 135),
        rule=(65, 65, 90),
    ),
    Palette(
        background=(26, 20, 16),
        foreground=(240, 232, 222),
        accent=(224, 150, 60),  # saturated amber
        muted=(135, 120, 105),
        rule=(85, 70, 55),
    ),
)


def palette_for(architecture: str, episode_id: int) -> Palette:
    """Deterministic: the same architecture string always yields the
    same Palette, across processes and across runs -- not just within
    one. Seeded from `hashlib.sha256(architecture)`, not builtin
    `hash()`: `hash()` on a str is salted per-process
    (`PYTHONHASHSEED`) specifically so it *isn't* stable across runs,
    which is the opposite of what a deterministic card style needs --
    using it here would silently give a different palette every time
    this process restarts, defeating the point.

    episode_id is accepted, not read -- see module docstring for why.
    Kept as a required parameter now so a later version that does fold
    in per-episode variation doesn't have to change every call site's
    signature to add it.
    """
    _ = episode_id
    digest = hashlib.sha256(architecture.encode("utf-8")).digest()
    seed = int.from_bytes(digest, "big")
    return random.Random(seed).choice(_PALETTES)
