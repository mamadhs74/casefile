"""Cards to video, via ffmpeg: render each card's PNG (cards.py), build
one zoompan/static clip per card, concatenate into a single silent mp4.

SCOPE BOUNDARY: no database access, no `packages.db` import, no LLM
calls, no `Shot`/`Asset` write. This module takes an already-planned,
timed, motion-assigned card sequence (`PlannedCard` from
packages.visual.planner, durations from timing.py, motions from
motion.py) and produces a video file; deciding what those cards should
be is earlier stages' job, not this module's.

ffmpeg invocation shape reused from experiments/slice_01/shots.py and
compose.py -- a working zoompan renderer that was actually measured
there (see that experiment's FINDINGS.md), not invented fresh here.
That module is itself throwaway and explicitly "not imported by
anything outside this experiment," so its *shape* is reused, not the
module itself. Reused as-is: h264_videotoolbox at a pinned
INTERMEDIATE_BITRATE for per-clip encodes; `-loop 1 -i` for a single
still source; `max(round(duration * FPS), 1)` frame-count math;
upscaling the source before zoompan so the filter has fractional-pixel
headroom (avoids visible integer-position stepping on a slow zoom);
and the concat demuxer + `-c copy` to stitch clips -- specifically
instead of filter_complex, which holds every input file open for the
whole graph at once, where concat demuxer processes one clip at a
time. That difference matters on the 8GB machine CLAUDE.md's stack
notes already name as a real constraint elsewhere in this project.

Changed from the reference, and why: the reference only ever builds
one motion -- a zoom from 1.0 up to a pinned end value, using
zoompan's own self-referencing `zoom` accumulator (which starts at 1.0
implicitly). This module has to support arbitrary zoom_start/zoom_end
(ZOOM_OUT runs 1.15 -> 1.0, the reverse direction) and a horizontal
pan at constant zoom (DRIFT), so the zoom and x expressions here are
built explicitly from ffmpeg's `on` (output frame number) instead: a
direct linear interpolation between zoom_start and zoom_end (and, for
pan, between -pan_x/2 and +pan_x/2 around center) that doesn't depend
on the accumulator's own undocumented starting value. Verified
empirically before writing this module, not just reasoned through:
rendered real zoompan and pan test clips and confirmed via ffprobe and
a first-frame/last-frame pixel comparison that the crop position
actually moves in the expected direction -- a filter chain can be
syntactically valid and exit 0 while still producing a frozen or
wrong-direction result, which only running it can catch.

ZOOMPAN_UPSCALE is 2, not the reference's 4: the reference's sources
were archival photos downscaled to ~1512px tall before that 4x
upscale; this module's sources are cards.py's own 3840x2160 renders,
already about 2x this module's 1080p output on their own, and the
zoom deltas used here (0.15 max, see motion.py) are half the
reference's 0.3 -- meaningfully less stepping risk to begin with, so
less upscale headroom is needed to avoid it. Timed against a real
cards.py render before picking this number: a 12s/360-frame zoompan
clip at UPSCALE=2 encodes in ~3.7s on this machine. Reusing 4 here
unmodified would upscale an already-4K source to roughly 15360x8640
per frame for no measured benefit.

STATIC cards skip zoompan entirely -- a plain scale to 1920x1080, no
per-frame filter graph -- per the task's own instruction: a zoompan
with zoom=1.0 would re-encode identically to a plain scale at higher
cost for zero visual difference.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from packages.domain.enums import MotionType
from packages.visual.cards import (
    AttributionCardSpec,
    ChapterTitleSpec,
    StatementCardSpec,
    TimelineSpec,
    render_attribution_card,
    render_chapter_title,
    render_statement_card,
    render_timeline,
)
from packages.visual.motion import validate_zoom_bounds
from packages.visual.palette import Palette
from packages.visual.planner import PlannedCard

OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
FPS = 30
ZOOMPAN_UPSCALE = 2
INTERMEDIATE_BITRATE = "20M"


class FfmpegNotFoundError(Exception):
    """Raised at import time if `ffmpeg` is not on PATH. No fallback,
    no silent skip -- this module has nothing useful to do without it."""

    def __init__(self, binary: str) -> None:
        self.binary = binary
        super().__init__(f"{binary!r} not found on PATH -- install ffmpeg.")


def _require_on_path(binary: str) -> str:
    resolved = shutil.which(binary)
    if resolved is None:
        raise FfmpegNotFoundError(binary)
    return resolved


FFMPEG_BIN = _require_on_path("ffmpeg")


class MismatchedLengthsError(Exception):
    """Raised when cards/durations/motions don't all describe the same
    number of cards -- there is no sensible way to render a card this
    function has no duration or motion for, or vice versa."""

    def __init__(self, cards: int, durations: int, motions: int) -> None:
        self.cards = cards
        self.durations = durations
        self.motions = motions
        super().__init__(
            f"cards ({cards}), durations ({durations}), and motions ({motions}) "
            "must all be the same length"
        )


def _render_card_image(card: PlannedCard, palette: Palette) -> Image.Image:
    spec = card.spec
    if isinstance(spec, ChapterTitleSpec):
        return render_chapter_title(spec, palette)
    if isinstance(spec, StatementCardSpec):
        return render_statement_card(spec, palette)
    if isinstance(spec, AttributionCardSpec):
        return render_attribution_card(spec, palette)
    if isinstance(spec, TimelineSpec):
        return render_timeline(spec, palette)
    raise AssertionError(f"unknown card spec type: {spec!r}")  # exhaustive above; see cards.py


def _zoompan_filter(params: dict[str, float], frames: int) -> str:
    """Explicit on-based linear interpolation -- see module docstring
    for why this doesn't use zoompan's self-referencing `zoom`
    accumulator the way the reference implementation does."""
    zoom_start = params.get("zoom_start", 1.0)
    zoom_end = params.get("zoom_end", 1.0)
    pan_x = params.get("pan_x", 0.0)

    if frames > 1:
        zoom_expr = f"{zoom_start}+({zoom_end}-{zoom_start})*on/{frames - 1}"
    else:
        zoom_expr = f"{zoom_start}"

    if pan_x and frames > 1:
        x_expr = f"iw/2-(iw/zoom/2)+iw*{pan_x}*(on/{frames - 1}-0.5)"
    else:
        x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"

    return (
        f"scale=iw*{ZOOMPAN_UPSCALE}:ih*{ZOOMPAN_UPSCALE},"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={frames}:s={OUTPUT_WIDTH}x{OUTPUT_HEIGHT}:fps={FPS}"
    )


def _encode_clip(
    image_path: Path,
    motion: MotionType,
    params: dict[str, float],
    duration: float,
    out_path: Path,
) -> None:
    frames = max(round(duration * FPS), 1)

    if motion == MotionType.STATIC:
        vf = f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}"
        rate_args = ["-r", str(FPS)]  # zoompan sets its own fps; a plain scale needs this instead
    else:
        validate_zoom_bounds(params)
        vf = _zoompan_filter(params, frames)
        rate_args = []

    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-loop", "1", "-i", str(image_path),
        "-vf", vf,
        "-frames:v", str(frames),
        *rate_args,
        "-c:v", "h264_videotoolbox",
        "-b:v", INTERMEDIATE_BITRATE,
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed encoding {out_path.name}:\n{result.stderr}")


def _concat_clips(clip_paths: Sequence[Path], list_path: Path, out_path: Path) -> None:
    list_path.write_text("".join(f"file '{p.resolve()}'\n" for p in clip_paths))

    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c", "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed:\n{result.stderr}")


def render_cards(
    cards: Sequence[PlannedCard],
    palette: Palette,
    durations: Sequence[float],
    motions: Sequence[tuple[MotionType, dict[str, float]]],
    out_dir: Path,
) -> Path:
    if not (len(cards) == len(durations) == len(motions)):
        raise MismatchedLengthsError(len(cards), len(durations), len(motions))

    out_dir.mkdir(parents=True, exist_ok=True)

    clip_paths: list[Path] = []
    for i, card in enumerate(cards):
        image = _render_card_image(card, palette)
        image_path = out_dir / f"card_{i:04d}.png"
        image.save(image_path)

        motion, params = motions[i]
        clip_path = out_dir / f"clip_{i:04d}.mp4"
        _encode_clip(image_path, motion, params, durations[i], clip_path)
        clip_paths.append(clip_path)

    final_path = out_dir / "cards.mp4"
    _concat_clips(clip_paths, out_dir / "concat_list.txt", final_path)
    return final_path
