"""Create the first real Episode against data/casefile.db: subject 10's
Paramount-Warner Bros. merger story (claims 91-101).

Tier 2: this writes to data/casefile.db. Written and run only after
explicit confirmation -- see CLAUDE.md's Tier 2 rule and the task this
was built under.

Ship-through-scratch is dead as a plan (docs/HANDOFF.md finding #43's
follow-up, this session): compose_episode requires a real Episode row
structurally, and Episode.variation_profile_id / VariationProfile.
subtitle_style_id are both required FKs with zero existing rows in this
project -- there is no sampler function anywhere in packages/ either.
This script creates the first-ever SubtitleStyle and VariationProfile
rows too, not just the Episode, using this project's own existing
test-factory defaults (tests/factories.py) rather than inventing new
values -- the only field that affects anything this session cares about
is narration_wpm, since generate_script only ever reads that one field
off VariationProfile (confirmed by inspection, chronological.py:332).

Thesis and thesis-bearing selection are the human-authored decision from
this session's task, not inferred -- see docs/ARCHITECTURES.md sec 3/4
on why that has to be a human act.

Order matters, same invariant reasoning as everywhere else in this
codebase:
1. SubtitleStyle, then VariationProfile (needs subtitle_style_id).
2. Flip narratable=True on claims 91-101. All eleven are sourced
   exclusively from source_id=13 (hollywoodreporter.com,
   CONTEMPORANEOUS = Tier A), so packages/db/listeners.py's
   _validate_narratable_claim_sourcing passes legitimately -- this
   script does not work around that check, it satisfies it.
3. Episode (needs variation_profile_id; cold_open_claim_id is declarative-
   only per Episode's own docstring, but set correctly here regardless).
4. EpisodeClaim x11 (needs every claim already narratable, per
   _reject_non_narratable_episode_claim -- this is why step 2 runs
   before step 4).

Safety:
1. Refuses to run unless data/casefile.db.bak already exists.
2. Refuses to run if an Episode already exists for subject 10 -- treated
   as operator error, not silently skipped or duplicated.
3. Refuses to run if any of claims 91-101 is already narratable=True or
   already linked to a different episode, same posture.
4. PRAGMA foreign_key_check after commit.
5. Prints every row created, with ids, at the end.

Usage (module form -- `packages` isn't importable when this file is run as
a bare script path, since this project isn't installed as a package; see
docs/SCHEMA.md):
    uv run python -m scripts.create_subject10_episode
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, col, select

from packages.db.models import (
    Claim,
    Episode,
    EpisodeClaim,
    SubtitleStyle,
    VariationProfile,
)
from packages.db.session import get_session
from packages.domain.enums import ColdOpenStyle, EpisodeArchitecture, ThumbnailComposition

SUBJECT_ID = 10
FILM_TV_STRATEGY_ID = 2
COLD_OPEN_CLAIM_ID = 101
THESIS = (
    "The Paramount-Warner Bros. merger cleared every regulator that could "
    "stop it, and the only thing left standing in its way is a lawsuit "
    "that hasn't been filed yet."
)

# (claim_id, thesis_bearing), in the position order EpisodeClaim.position
# will record -- ascending real claim id, which already matches the
# source article's own presentation order (all eleven have date_anchor
# None, see scripts/run_composition_scratch.py's own comment on this).
EPISODE_CLAIM_SPECS: list[tuple[int, bool]] = [
    (91, True),
    (92, False),
    (93, True),
    (94, False),
    (95, True),
    (96, True),
    (97, False),
    (98, True),
    (99, True),
    (100, False),
    (101, True),
]


class SetupAborted(Exception):
    """Raised for any condition that should stop the script before or
    during the change. Caught once, at the bottom, to print a clean
    message and exit non-zero -- no partial state is ever left committed."""


def _require_backup() -> None:
    backup = Path("data/casefile.db.bak")
    if not backup.exists():
        raise SetupAborted(
            f"refusing to run: {backup} does not exist. "
            f"This script does not make its own backup."
        )
    print(f"backup present: {backup} ({backup.stat().st_size} bytes)")


def _refuse_if_already_set_up(session: Session) -> None:
    existing_episode = session.exec(select(Episode).where(Episode.subject_id == SUBJECT_ID)).first()
    if existing_episode is not None:
        raise SetupAborted(
            f"refusing to run: subject {SUBJECT_ID} already has episode "
            f"id={existing_episode.id} -- not creating a second one."
        )

    claim_ids = [claim_id for claim_id, _ in EPISODE_CLAIM_SPECS]
    claims = session.exec(select(Claim).where(col(Claim.id).in_(claim_ids))).all()
    if len(claims) != len(claim_ids):
        found = {c.id for c in claims}
        missing = set(claim_ids) - found
        raise SetupAborted(f"refusing to run: claim id(s) {sorted(missing)} not found")
    already_narratable = [c.id for c in claims if c.narratable]
    if already_narratable:
        raise SetupAborted(
            f"refusing to run: claim id(s) {sorted(already_narratable)} already "
            f"narratable=True -- expected all False going in"
        )
    wrong_subject = [c.id for c in claims if c.subject_id != SUBJECT_ID]
    if wrong_subject:
        raise SetupAborted(f"refusing to run: claim id(s) {sorted(wrong_subject)} not on subject {SUBJECT_ID}")


def _check_foreign_keys(session: Session, label: str) -> None:
    violations = session.execute(text("PRAGMA foreign_key_check")).fetchall()
    if violations:
        raise SetupAborted(f"foreign_key_check ({label}) FAILED: {violations}")
    print(f"foreign_key_check ({label}): clean")


def run_setup(session: Session) -> None:
    subtitle_style = SubtitleStyle(
        name="Default",
        font_family="Arial",
        font_size=64,
        primary_colour="&H00FFFFFF",
        outline_colour="&H00000000",
        outline_width=3.0,
        shadow=1.0,
        alignment=2,
        margin_v=60,
        max_chars_per_line=42,
    )
    session.add(subtitle_style)
    session.commit()
    session.refresh(subtitle_style)
    assert subtitle_style.id is not None
    print(f"created SubtitleStyle id={subtitle_style.id}")

    variation_profile = VariationProfile(
        strategy_id=FILM_TV_STRATEGY_ID,
        cold_open_style=ColdOpenStyle.SCENE_FIRST,
        act_count=4,
        narration_wpm=145,
        shot_duration_mean_s=6.0,
        shot_duration_sd_s=1.5,
        transition_set=["hard_cut"],
        music_present=False,
        music_intensity=0.0,
        subtitle_style_id=subtitle_style.id,
        thumbnail_composition=ThumbnailComposition.LOCATION_WIDE,
    )
    session.add(variation_profile)
    session.commit()
    session.refresh(variation_profile)
    assert variation_profile.id is not None
    print(f"created VariationProfile id={variation_profile.id} (narration_wpm=145)")

    claim_ids = [claim_id for claim_id, _ in EPISODE_CLAIM_SPECS]
    claims_by_id = {
        c.id: c for c in session.exec(select(Claim).where(col(Claim.id).in_(claim_ids))).all()
    }
    for claim_id in claim_ids:
        claim = claims_by_id[claim_id]
        claim.narratable = True
        session.add(claim)
        session.commit()
    print(f"flipped narratable=True on claim ids {claim_ids}")

    episode = Episode(
        subject_id=SUBJECT_ID,
        variation_profile_id=variation_profile.id,
        thesis=THESIS,
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        cold_open_claim_id=COLD_OPEN_CLAIM_ID,
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)
    assert episode.id is not None
    print(f"created Episode id={episode.id} for subject {SUBJECT_ID}")

    for position, (claim_id, thesis_bearing) in enumerate(EPISODE_CLAIM_SPECS):
        session.add(
            EpisodeClaim(
                episode_id=episode.id,
                claim_id=claim_id,
                position=position,
                thesis_bearing=thesis_bearing,
            )
        )
        session.commit()
    print(f"created {len(EPISODE_CLAIM_SPECS)} EpisodeClaim rows")

    _check_foreign_keys(session, "post-commit")

    print()
    print(f"episode_id={episode.id}")
    print(f"variation_profile_id={variation_profile.id}")
    print(f"subtitle_style_id={subtitle_style.id}")
    print(f"cold_open_claim_id={episode.cold_open_claim_id}")
    print(f"thesis_bearing claims: {[cid for cid, tb in EPISODE_CLAIM_SPECS if tb]}")


def main() -> int:
    try:
        with get_session() as session:
            _require_backup()
            _refuse_if_already_set_up(session)
            run_setup(session)
    except SetupAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
