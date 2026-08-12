"""First end-to-end packages/visual run against real claims: subject
8's Lizzie Borden material (date_anchor LIKE '1893%'), through
plan_cards -> assign_durations -> assign_motion -> render_cards, to a
real mp4 in data/renders/scratch_visual_narrated/.

Extended to add real narration: this script now synthesizes actual
speech per card (packages/voice/say_provider.py), measures its real
duration via ffprobe, and uses those MEASURED durations to drive
render_cards -- not assign_durations' word-count estimate.
assign_durations is still called once, but only to report how far that
estimate drifts from real speech now that real audio exists to compare
against. That comparison, not the video itself, is the actual point of
this run: it's what decides whether forced alignment is needed before
this pipeline can be trusted at word-count timing alone.

SCOPE: read-only database access. SELECT only -- the engine below is
opened in SQLite's own read-only URI mode (confirmed empirically to
raise sqlite3.OperationalError on a write attempt, not just documented
as read-only, before this script was written), so a stray write
anywhere in this script or anything it calls fails loudly instead of
silently landing on the real database. No LLM calls; no migration; no
schema change.

Subject 8 is a contaminated fixture holding sources from three
unrelated cases (docs/HANDOFF.md sec 8) -- the date_anchor LIKE
'1893%' filter is what isolates the Lizzie Borden material (source_7)
from the other two, and it is deliberate, not an arbitrary narrowing:
checked directly against the real data before writing this script --
every one of subject 8's Borden claims that carries a date_anchor at
all is anchored to 1893-06-20, the single date the one Boston Globe
article behind source_7 reports on. This filter is the actual boundary
between the Borden material and the two other cases sharing this
subject row, not a subset of a larger Borden pool. Do not widen it.

Every one of these claims has section=NULL (docs/SCHEMA.md: no source
for subject 8 has ever gone through the one-time Ground/Resolution
tagging pass) and a non-null date_anchor, so plan_cards' rule 2 fires
for every claim without exception -- expect an all-timeline card plan,
not a mix. That is what the real data produces, not a bug in this
script.

Usage:
    uv run python -m scripts.render_scratch_visual
"""

from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine
from sqlmodel import Session, col, select

from packages.db.models import Claim, ClaimSource, Source
from packages.visual.cards import ChapterTitleSpec
from packages.visual.motion import assign_motion
from packages.visual.palette import palette_for
from packages.visual.planner import ClaimRecord, PlannedCard, plan_cards
from packages.visual.render import FFMPEG_BIN, render_cards
from packages.visual.timing import CHAPTER_TITLE_SECONDS, assign_durations, total_runtime
from packages.voice.say_provider import SayProvider

DB_PATH = Path("data/casefile.db")
OUT_DIR = Path("data/renders/scratch_visual_narrated")

# Deliberate, non-negotiable -- see module docstring.
SUBJECT_ID = 8
DATE_PREFIX = "1893"

# No real Episode exists for this scratch run -- there is nothing to
# read an architecture off of, so this is asserted directly, the same
# way earlier scratch scripts in this project (e.g.
# scripts/run_composition_scratch.py) assert EpisodeArchitecture.CHRONOLOGICAL
# for a synthetic episode rather than deriving it from a real row.
ARCHITECTURE = "chronological"

CARD_KINDS = ("chapter_title", "statement", "attribution", "timeline")

# Matches SayProvider's own real output format exactly -- checked via
# ffprobe against a real synthesized clip before writing this, not
# assumed. The concat demuxer's -c copy step below requires every
# input clip to share codec, sample rate, and channel layout, and the
# silent chapter-title clips are generated independently of say's own
# output, so this has to be pinned rather than left to ffmpeg defaults
# that might not agree with it.
SILENT_SAMPLE_RATE = 22050
SILENT_CHANNELS = "mono"

LONGEST_CARDS_TO_REPORT = 5


def _fetch_claim_records(session: Session) -> tuple[list[ClaimRecord], int]:
    """Returns (records, labeled_count) -- labeled_count is how many
    claims joined to a real Source (and so got a real source_label),
    for the printed report. LEFT JOIN, not JOIN: a claim with no
    ClaimSource row (shouldn't happen for these 22, per docs/SCHEMA.md's
    "exactly one ClaimSource per claim" invariant, but not assumed
    without checking) must still appear with source_label=None rather
    than being silently dropped from the plan."""
    query = (
        select(Claim, Source.publisher)
        .join(ClaimSource, col(ClaimSource.claim_id) == col(Claim.id), isouter=True)
        .join(Source, col(Source.id) == col(ClaimSource.source_id), isouter=True)
        .where(
            Claim.subject_id == SUBJECT_ID,
            col(Claim.date_anchor).like(f"{DATE_PREFIX}%"),
        )
        .order_by(col(Claim.id))
    )
    rows = session.exec(query).all()

    records: list[ClaimRecord] = []
    labeled_count = 0
    for claim, publisher in rows:
        assert claim.id is not None  # a queried, persisted row always has one
        if publisher is not None:
            labeled_count += 1
        records.append(
            ClaimRecord(
                claim_id=claim.id,
                statement=claim.statement,
                claim_type=claim.claim_type.name,  # .name == "FACT", matching planner.py's literal
                section=None,
                date_anchor=claim.date_anchor,
                source_label=publisher,
            )
        )
    return records, labeled_count


def _format_mmss(seconds: float) -> str:
    minutes, remainder = divmod(int(round(seconds)), 60)
    return f"{minutes}:{remainder:02d}"


def _report_card_counts(cards: list[PlannedCard]) -> None:
    counts = Counter(card.kind for card in cards)
    print(f"cards planned: {len(cards)}")
    for kind in CARD_KINDS:
        print(f"  {kind}: {counts.get(kind, 0)}")


def _card_narration_text(card: PlannedCard) -> str | None:
    """None for chapter_title cards -- they carry no narration, a
    silent clip is generated instead (see _generate_silent_wav). Every
    other card's spec carries a `.statement` field -- same isinstance
    pattern packages/visual/timing.py's own _statement_text uses,
    since ChapterTitleSpec is the one spec type without one."""
    spec = card.spec
    if isinstance(spec, ChapterTitleSpec):
        return None
    return spec.statement


def _generate_silent_wav(duration: float, out_path: Path) -> None:
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-f", "lavfi", "-i", f"anullsrc=r={SILENT_SAMPLE_RATE}:cl={SILENT_CHANNELS}",
        "-t", str(duration),
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed generating silent WAV {out_path.name}:\n{result.stderr}"
        )


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _synthesize_narration(cards: list[PlannedCard], out_dir: Path) -> list[Path]:
    """One WAV per card, in card order -- real speech via SayProvider
    for statement/attribution/timeline cards, a silent
    CHAPTER_TITLE_SECONDS clip for chapter_title cards."""
    provider = SayProvider()
    paths: list[Path] = []
    for i, card in enumerate(cards):
        out_path = out_dir / f"narration_{i:04d}.wav"
        text = _card_narration_text(card)
        if text is None:
            _generate_silent_wav(CHAPTER_TITLE_SECONDS, out_path)
        else:
            provider.synthesize(text, out_path)
        paths.append(out_path)
    return paths


def _concat_audio(clip_paths: list[Path], list_path: Path, out_path: Path) -> None:
    list_path.write_text("".join(f"file '{p.resolve()}'\n" for p in clip_paths))

    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c", "copy",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio concat failed:\n{result.stderr}")


def _mux_narration(video_path: Path, audio_path: Path, out_path: Path) -> None:
    """-c:v copy -- the silent video from render_cards is not
    re-encoded, only muxed with the narration track. Audio goes to AAC,
    the standard mp4 delivery codec (PCM in an mp4 container is legal
    but not what any real player expects)."""
    cmd = [
        FFMPEG_BIN, "-y", "-hide_banner", "-v", "warning",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed:\n{result.stderr}")


def _report_longest_cards(
    cards: list[PlannedCard], estimated: list[float], measured: list[float]
) -> None:
    longest_indices = sorted(
        range(len(cards)), key=lambda i: measured[i], reverse=True
    )[:LONGEST_CARDS_TO_REPORT]

    print(f"{LONGEST_CARDS_TO_REPORT} longest cards (by measured duration):")
    for i in longest_indices:
        diff = measured[i] - estimated[i]
        print(
            f"  [{i:>2}] {cards[i].kind:<13} claim_id={cards[i].claim_id!s:<5} "
            f"estimated={estimated[i]:7.3f}s  measured={measured[i]:7.3f}s  diff={diff:+7.3f}s"
        )


def main() -> None:
    engine = create_engine(f"sqlite:///file:{DB_PATH}?mode=ro&uri=true")
    with Session(engine) as session:
        records, labeled_count = _fetch_claim_records(session)

    print(
        f"claims pulled (subject_id={SUBJECT_ID}, "
        f"date_anchor LIKE '{DATE_PREFIX}%'): {len(records)}"
    )

    cards = plan_cards(records)
    _report_card_counts(cards)

    estimated_durations = assign_durations(cards)
    estimated_runtime = total_runtime(estimated_durations)
    print(
        f"total estimated runtime (assign_durations): {estimated_runtime:.3f}s "
        f"({_format_mmss(estimated_runtime)})"
    )

    motions = assign_motion(cards, ARCHITECTURE)
    print(f"claims with a real source_label: {labeled_count}/{len(records)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    narration_paths = _synthesize_narration(cards, OUT_DIR)
    measured_durations = [_probe_duration(p) for p in narration_paths]
    measured_runtime = total_runtime(measured_durations)
    print(
        f"total measured runtime (real audio): {measured_runtime:.3f}s "
        f"({_format_mmss(measured_runtime)})"
    )

    diff_seconds = measured_runtime - estimated_runtime
    diff_percent = (diff_seconds / estimated_runtime * 100) if estimated_runtime else 0.0
    print(f"estimate vs. measured: {diff_seconds:+.3f}s ({diff_percent:+.1f}%)")

    _report_longest_cards(cards, estimated_durations, measured_durations)

    # episode_id is unused by palette_for in v1 -- see that function's
    # own docstring. 0 is arbitrary; no real Episode exists here.
    palette = palette_for(ARCHITECTURE, episode_id=0)
    silent_video_path = render_cards(cards, palette, measured_durations, motions, OUT_DIR)

    narration_track_path = OUT_DIR / "narration.wav"
    _concat_audio(narration_paths, OUT_DIR / "narration_concat_list.txt", narration_track_path)

    final_path = OUT_DIR / "cards_narrated.mp4"
    _mux_narration(silent_video_path, narration_track_path, final_path)

    print(f"output: {final_path}")


if __name__ == "__main__":
    main()
