"""Render the section-level card binding for any real Episode -- one
card per SECTION (Ground, Sequence, Resolution), not one per claim and
not one per composed sentence. Generalizes scripts/render_episode1.py
(kept, not deleted, per the task this was built under) to take
--episode-id instead of being pinned to episode 1.

SECTION TEXT SOURCE: outputs/<episode_id>/composed_script.json,
written by scripts/compose_episode.py on a full successful composition
run. UNLIKE render_episode1.py, there is no fallback stand-in prose
here -- that existed to prove the render path end to end while Gemini
was down, and the path is proven (see docs/HANDOFF.md). This script
fails loudly (MissingComposedScriptError) if that file doesn't exist,
rather than silently rendering placeholder text as if it were real.

Card binding is coarser than either of the two original scratch
scripts: one PlannedCard per SECTION here, versus one per claim
(render_scratch_visual.py, untouched by this script -- still pinned to
subject 8) or one per composed sentence (compose_scratch_borden.py).
Each section's full text is synthesized as exactly ONE Kokoro clip;
that clip's measured (ffprobe) duration becomes that card's on-screen
duration directly. There is no separate "proportional" calculation to
write -- the measured duration of a section's own audio already *is*
its proportional share of the total runtime. assign_durations (the
word-count estimate) is never called anywhere in this script.

Reuses scripts/render_scratch_visual.py's helpers by import only
(_synthesize_narration, _probe_duration, _concat_audio, _mux_narration,
_format_mmss) -- same precedent as scripts/compose_scratch_borden.py
and scripts/render_episode1.py. That file is not edited.

Scope, deliberately untouched (see the task this was built under):
- packages/db/models.py -- no changes here (a real column was added
  elsewhere this session, but not by this script).
- ScriptCitation -- no span offsets added; this script has no citation
  concept at all, it renders three fixed text blocks, not claims.
- No Gemini calls -- composition is a separate, earlier stage
  (scripts/compose_episode.py).

Output filename is final.mp4, not episodeN_sections.mp4 -- matches
outputs/<run_id>/'s expected contents for Task 4
(scripts/run_episode.py), which this script's render_episode() is
built to be called from directly.

Kokoro is local and free: rerun as many times as needed while
iterating on card/motion/palette details.

Usage:
    uv run python -m scripts.render_episode --episode-id 1
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from packages.visual.cards import StatementCardSpec
from packages.visual.motion import assign_motion
from packages.visual.palette import palette_for
from packages.visual.planner import PlannedCard
from packages.visual.render import render_cards
from packages.visual.timing import total_runtime
from packages.voice.kokoro_provider import DEFAULT_VOICE_NAME
from scripts.render_scratch_visual import (
    _concat_audio,
    _format_mmss,
    _mux_narration,
    _probe_duration,
    _synthesize_narration,
)

ARCHITECTURE = "chronological"


class MissingComposedScriptError(Exception):
    """composed_script.json doesn't exist for this episode yet -- run
    scripts/compose_episode.py --episode-id <id> first. No fallback
    text here; see module docstring for why."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(
            f"{path} not found -- run "
            f"`uv run python -m scripts.compose_episode --episode-id ...` first"
        )


def _load_sections(composed_script_path: Path) -> list[tuple[str, str]]:
    """composed_script.json is only ever written by
    scripts/compose_episode.py's _write_output, and only on a fully
    successful compose_episode run -- so its presence implies all three
    fields below are populated; no partial-file handling here."""
    if not composed_script_path.exists():
        raise MissingComposedScriptError(composed_script_path)
    payload = json.loads(composed_script_path.read_text())
    print(f"section text source: {composed_script_path} (real composed text)")
    return [
        ("Ground", payload["ground"]),
        ("Sequence", payload["sequence"]),
        ("Resolution", payload["resolution"]),
    ]


def _build_cards(sections: list[tuple[str, str]]) -> list[PlannedCard]:
    return [
        PlannedCard(kind="statement", claim_id=None, spec=StatementCardSpec(statement=text))
        for _name, text in sections
    ]


def render_episode(episode_id: int, output_dir: Path, *, voice: str = DEFAULT_VOICE_NAME) -> Path:
    """Importable entry point -- scripts/run_episode.py (Task 4) calls
    this directly with its own output_dir (outputs/<run_id>/) instead
    of shelling out to main(). Raises MissingComposedScriptError if
    composed_script.json isn't there; caller decides how to report/
    record that. Returns the final.mp4 path on success."""
    composed_script_path = output_dir / "composed_script.json"
    sections = _load_sections(composed_script_path)

    total_words = sum(len(text.split()) for _name, text in sections)
    print(f"section text: {total_words} words across {len(sections)} sections")
    for name, text in sections:
        print(f"  {name}: {len(text.split())} words")

    cards = _build_cards(sections)

    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"synthesizing {len(cards)} clips (voice={voice})...")
    synthesis_start = time.perf_counter()
    narration_paths = _synthesize_narration(cards, output_dir, voice)
    synthesis_elapsed = time.perf_counter() - synthesis_start
    print(
        f"synthesis wall-clock time: {synthesis_elapsed:.3f}s ({_format_mmss(synthesis_elapsed)})"
    )

    measured_durations = [_probe_duration(p) for p in narration_paths]
    for (name, _text), duration in zip(sections, measured_durations, strict=True):
        print(f"  {name}: measured {duration:.3f}s")
    measured_runtime = total_runtime(measured_durations)
    print(f"total measured runtime: {measured_runtime:.3f}s ({_format_mmss(measured_runtime)})")

    motions = assign_motion(cards, ARCHITECTURE)
    palette = palette_for(ARCHITECTURE, episode_id=episode_id)
    silent_video_path = render_cards(cards, palette, measured_durations, motions, output_dir)

    narration_track_path = output_dir / "narration.wav"
    _concat_audio(narration_paths, output_dir / "narration_concat_list.txt", narration_track_path)

    final_path = output_dir / "final.mp4"
    _mux_narration(silent_video_path, narration_track_path, final_path)

    final_duration = _probe_duration(final_path)
    print(f"output: {final_path}")
    print(f"final duration (ffprobe): {final_duration:.3f}s ({_format_mmss(final_duration)})")
    return final_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-id", type=int, required=True)
    parser.add_argument("--voice", default=DEFAULT_VOICE_NAME)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output_dir = Path(f"outputs/{args.episode_id}")
    try:
        render_episode(args.episode_id, output_dir, voice=args.voice)
    except MissingComposedScriptError as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
