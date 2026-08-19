"""Render the section-level card binding for Episode 1 (subject 10,
the Paramount-Warner Bros. merger story) -- one card per SECTION
(Ground, Sequence, Resolution), not one per claim and not one per
composed sentence. Proves the render path end to end while Gemini is
down (docs/HANDOFF.md), using hand-written stand-in prose in place of
real composed text.

STAND-IN TEXT: GROUND_TEXT / SEQUENCE_TEXT / RESOLUTION_TEXT below are
hand-written, not Gemini output -- roughly 200 words total, split to
match generate_script's own budgeted proportions for episode_id=1
(Ground 20 / Sequence 129 / Resolution 28 words -- see
scripts/create_subject10_episode.py and scripts/compose_subject10_episode.py,
which hit a 503 before producing real text). Editable by hand between
runs, same posture as compose_scratch_borden.py's own THESIS constant.
Swap these for Episode 1's real composed text once compose_episode
succeeds against real Gemini.

Card binding is coarser than either existing scratch script: one
PlannedCard per SECTION here, versus one per claim
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
_format_mmss) -- same precedent as scripts/compose_scratch_borden.py.
That file is not edited.

Scope, deliberately untouched (see the task this was built under):
- packages/db/models.py -- no changes, no migration.
- ScriptCitation -- no span offsets added; this script has no citation
  concept at all, it renders three fixed text blocks, not claims.
- No Gemini calls -- this is exactly why this script exists right now.

Kokoro is local and free: rerun as many times as needed while
iterating on card/motion/palette details.

Usage:
    uv run python -m scripts.render_episode1
"""

from __future__ import annotations

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

OUT_DIR = Path("data/renders/episode1")

EPISODE_ID = 1
ARCHITECTURE = "chronological"

# Hand-written stand-in prose -- see module docstring. Not Gemini
# output. Section order fixed: Ground, Sequence, Resolution.
GROUND_TEXT = (
    "By late 2026, Paramount was nearing completion of a $111 billion "
    "takeover of Warner Bros., a deal that would reshape the American "
    "media landscape."
)

SEQUENCE_TEXT = (
    "The European Commission signaled it would approve the merger, but "
    "only if Paramount gave up its joint venture with Universal "
    "Pictures. A Paramount spokesperson said the company had engaged "
    "constructively with regulators and law enforcement worldwide. "
    "Paramount's legal chief, Makan Delrahim, argued publicly that "
    "regulators understood the deal as procompetitive against the "
    "reach of the biggest technology platforms. Separately, reporting "
    "surfaced that Larry Ellison, whose family controls Paramount, had "
    "donated roughly forty five million dollars to a political group "
    "backing Donald Trump's 2024 campaign. And even as approvals "
    "accumulated from continent to continent, a coalition of states "
    "led by California began preparing a lawsuit, expected within a "
    "month, to challenge and block the merger outright."
)

RESOLUTION_TEXT = (
    "Regulators in China, South Africa, Saudi Arabia, Ukraine, Serbia, "
    "and North Macedonia all cleared the deal. The Justice Department "
    "signed off too, finding no market harm and requiring no "
    "divestitures anywhere in the settlement."
)

SECTIONS: list[tuple[str, str]] = [
    ("Ground", GROUND_TEXT),
    ("Sequence", SEQUENCE_TEXT),
    ("Resolution", RESOLUTION_TEXT),
]


def _build_cards() -> list[PlannedCard]:
    return [
        PlannedCard(kind="statement", claim_id=None, spec=StatementCardSpec(statement=text))
        for _name, text in SECTIONS
    ]


def main() -> int:
    total_words = sum(len(text.split()) for _name, text in SECTIONS)
    print(f"stand-in text: {total_words} words across {len(SECTIONS)} sections")
    for name, text in SECTIONS:
        print(f"  {name}: {len(text.split())} words")

    cards = _build_cards()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"synthesizing {len(cards)} clips (voice={DEFAULT_VOICE_NAME})...")
    synthesis_start = time.perf_counter()
    narration_paths = _synthesize_narration(cards, OUT_DIR, DEFAULT_VOICE_NAME)
    synthesis_elapsed = time.perf_counter() - synthesis_start
    print(f"synthesis wall-clock time: {synthesis_elapsed:.3f}s ({_format_mmss(synthesis_elapsed)})")

    measured_durations = [_probe_duration(p) for p in narration_paths]
    for (name, _text), duration in zip(SECTIONS, measured_durations, strict=True):
        print(f"  {name}: measured {duration:.3f}s")
    measured_runtime = total_runtime(measured_durations)
    print(f"total measured runtime: {measured_runtime:.3f}s ({_format_mmss(measured_runtime)})")

    motions = assign_motion(cards, ARCHITECTURE)
    palette = palette_for(ARCHITECTURE, episode_id=EPISODE_ID)
    silent_video_path = render_cards(cards, palette, measured_durations, motions, OUT_DIR)

    narration_track_path = OUT_DIR / "narration.wav"
    _concat_audio(narration_paths, OUT_DIR / "narration_concat_list.txt", narration_track_path)

    final_path = OUT_DIR / "episode1_sections.mp4"
    _mux_narration(silent_video_path, narration_track_path, final_path)

    final_duration = _probe_duration(final_path)
    print(f"output: {final_path}")
    print(f"final duration (ffprobe): {final_duration:.3f}s ({_format_mmss(final_duration)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
