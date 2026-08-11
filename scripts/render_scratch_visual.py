"""First end-to-end packages/visual run against real claims: subject
8's Lizzie Borden material (date_anchor LIKE '1893%'), through
plan_cards -> assign_durations -> assign_motion -> render_cards, to a
real mp4 in data/renders/scratch_visual/.

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

from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine
from sqlmodel import Session, col, select

from packages.db.models import Claim, ClaimSource, Source
from packages.visual.motion import assign_motion
from packages.visual.palette import palette_for
from packages.visual.planner import ClaimRecord, PlannedCard, plan_cards
from packages.visual.render import render_cards
from packages.visual.timing import assign_durations, total_runtime

DB_PATH = Path("data/casefile.db")
OUT_DIR = Path("data/renders/scratch_visual")

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

    durations = assign_durations(cards)
    runtime = total_runtime(durations)
    print(f"total runtime: {runtime:.3f}s ({_format_mmss(runtime)})")

    motions = assign_motion(cards, ARCHITECTURE)

    print(f"claims with a real source_label: {labeled_count}/{len(records)}")

    # episode_id is unused by palette_for in v1 -- see that function's
    # own docstring. 0 is arbitrary; no real Episode exists here.
    palette = palette_for(ARCHITECTURE, episode_id=0)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = render_cards(cards, palette, durations, motions, OUT_DIR)

    print(f"output: {out_path}")


if __name__ == "__main__":
    main()
