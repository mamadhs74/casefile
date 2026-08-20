"""Parameterized episode creation -- generalizes
scripts/create_subject10_episode.py (kept, not deleted, per the task
this was built under) into a reusable script taking --subject-id and
--thesis instead of hardcoded subject-10-specific constants.

Tier 2: a real (non-dry-run) run writes to data/casefile.db. Written and
run only after explicit confirmation -- see CLAUDE.md's Tier 2 rule.

CLAIM POOL: a source "qualifies" for a subject if it has at least one
claim tagged Section.RESOLUTION. The pool is every claim (any section,
including untagged/Sequence) sourced from a qualifying source. Not
"every claim tagged GROUND or RESOLUTION" (too narrow -- Sequence would
be nearly empty, just the cold-open claim) and not "every claim for the
subject" (too wide -- would pull in every other unrelated story the
subject's other sources cover). Verified by hand against subject 10,
real data: source 13 (the Paramount-Warner Bros. merger) has a
RESOLUTION claim, so it qualifies; source 16 (the Venice Film Festival
lineup) has a GROUND claim but no RESOLUTION claim, so it does NOT
qualify, and its 6 claims are excluded from the pool. This rule is also
a real, principled distinction, not just curve-fit to reproduce
episode 1: a story with setup but no outcome isn't an episode's worth
of material yet -- see docs/HANDOFF.md finding #43.

THESIS-BEARING: every pool claim tagged GROUND or RESOLUTION.

COLD OPEN: the pool's last RESOLUTION-tagged claim, by id.

VariationProfile/SubtitleStyle are NOT created per episode -- both are
reused by id (VARIATION_PROFILE_ID / SUBTITLE_STYLE_ID below), per the
task's own instruction. A real run refuses if either row doesn't
already exist rather than silently creating a fresh one --
scripts/create_subject10_episode.py's own first-ever run is what
created id=1 for both; this script assumes that already happened.

NARRATABLE: only pool claims are ever flipped, and only claims still
False are touched -- a pool claim that's already narratable=True
(expected the moment a second episode reuses an overlapping pool, since
narratable is claim-intrinsic and amortizes across episodes by design,
per docs/SCHEMA.md) is left alone, not treated as an error. This is a
deliberate difference from scripts/create_subject10_episode.py's own
stricter "refuse if anything is already narratable" check, which made
sense for a guaranteed-first-ever run against a guaranteed-clean pool
but not for a script meant to run more than once.

--dry-run: computes the pool, thesis-bearing set, cold-open claim, and
the real generate_script allocation, and prints all of it -- without
ever committing. Mechanically: every write (narratable flips, Episode,
EpisodeClaim) is session.flush()'d, never session.commit()'d, so
generate_script's own DB queries see them for the duration of this
process (confirmed by inspection: generate_script never calls flush or
commit itself, it only reads), then session.rollback() discards all of
it before exit. This calls the real generate_script function, not a
reimplementation, so there's no risk of the dry-run allocation logic
drifting from what a real run would actually produce. --dry-run also
bypasses the refuse-if-episode-exists guard below, since it never
persists a second episode.

A real (non-dry-run) run refuses if an Episode already exists for
--subject-id, unchanged from scripts/create_subject10_episode.py's own
posture -- creating a second real episode for a subject is a
deliberate, separate decision this script doesn't make silently.

Usage:
    uv run python -m scripts.create_episode --subject-id 10 --thesis "..." --dry-run
    uv run python -m scripts.create_episode --subject-id 10 --thesis "..."
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text
from sqlmodel import Session, SQLModel, col, select

from packages.db.models import (
    Claim,
    ClaimSource,
    Episode,
    EpisodeClaim,
    SubtitleStyle,
    VariationProfile,
)
from packages.db.session import get_session
from packages.domain.enums import EpisodeArchitecture, Section
from packages.script.chronological import generate_script

VARIATION_PROFILE_ID = 1
SUBTITLE_STYLE_ID = 1


class SetupAborted(Exception):
    """Raised for any condition that should stop the script before or
    during the change. Caught once, at the bottom, to print a clean
    message and exit non-zero -- no partial state is ever left
    committed (dry-run rolls back; a real run's abort happens before
    any commit call)."""


def _require_backup() -> None:
    backup = Path("data/casefile.db.bak")
    if not backup.exists():
        raise SetupAborted(
            f"refusing to run: {backup} does not exist. "
            f"This script does not make its own backup."
        )
    print(f"backup present: {backup} ({backup.stat().st_size} bytes)")


def _require_row_exists(session: Session, model: type[SQLModel], row_id: int, label: str) -> None:
    if session.get(model, row_id) is None:
        raise SetupAborted(
            f"refusing to run: {label} id={row_id} does not exist -- "
            f"run scripts/create_subject10_episode.py first"
        )


def _check_foreign_keys(session: Session, label: str) -> None:
    violations = session.execute(text("PRAGMA foreign_key_check")).fetchall()
    if violations:
        raise SetupAborted(f"foreign_key_check ({label}) FAILED: {violations}")
    print(f"foreign_key_check ({label}): clean")


def _qualifying_source_ids(session: Session, subject_id: int) -> list[int]:
    """Sources for this subject with at least one claim tagged
    Section.RESOLUTION -- see module docstring."""
    query = (
        select(ClaimSource.source_id)
        .join(Claim, col(Claim.id) == col(ClaimSource.claim_id))
        .where(Claim.subject_id == subject_id, Claim.section == Section.RESOLUTION)
        .distinct()
    )
    return list(session.exec(query).all())


def _claim_pool(session: Session, subject_id: int, source_ids: list[int]) -> list[Claim]:
    if not source_ids:
        return []
    query = (
        select(Claim)
        .join(ClaimSource, col(ClaimSource.claim_id) == col(Claim.id))
        .where(
            Claim.subject_id == subject_id,
            col(ClaimSource.source_id).in_(source_ids),
        )
        .distinct()
        .order_by(col(Claim.id))
    )
    return list(session.exec(query).all())


def _thesis_bearing_claim_ids(pool: list[Claim]) -> set[int]:
    ids: set[int] = set()
    for claim in pool:
        if claim.section in (Section.GROUND, Section.RESOLUTION):
            assert claim.id is not None
            ids.add(claim.id)
    return ids


def _cold_open_claim_id(pool: list[Claim]) -> int | None:
    resolution_ids = [claim.id for claim in pool if claim.section == Section.RESOLUTION]
    return max(resolution_ids) if resolution_ids else None  # type: ignore[type-var]


def _build_episode(
    session: Session,
    subject_id: int,
    thesis: str,
    pool: list[Claim],
    thesis_bearing_ids: set[int],
    cold_open_claim_id: int,
) -> Episode:
    """Flushes (never commits) narratable flips, an Episode row, and
    EpisodeClaim rows for every pool claim. Caller decides commit vs.
    rollback -- see module docstring on --dry-run."""
    flipped = 0
    for claim in pool:
        if not claim.narratable:
            claim.narratable = True
            session.add(claim)
            flipped += 1
    session.flush()
    print(f"narratable flipped: {flipped} claim(s) (rest already True)")

    episode = Episode(
        subject_id=subject_id,
        variation_profile_id=VARIATION_PROFILE_ID,
        thesis=thesis,
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        cold_open_claim_id=cold_open_claim_id,
    )
    session.add(episode)
    session.flush()
    assert episode.id is not None

    for position, claim in enumerate(pool):
        assert claim.id is not None
        session.add(
            EpisodeClaim(
                episode_id=episode.id,
                claim_id=claim.id,
                position=position,
                thesis_bearing=claim.id in thesis_bearing_ids,
            )
        )
    session.flush()
    return episode


def _report_allocation(
    episode_id: int, pool: list[Claim], thesis_bearing_ids: set[int], session: Session
) -> None:
    allocated = generate_script(session, episode_id, min_claim_count=len(pool))
    print()
    print("generate_script allocation:")
    print(f"  cold_open_claim: {allocated.cold_open_claim.claim_id}")
    print(f"  ground_claims: {[c.claim_id for c in allocated.ground_claims]}")
    print(f"  sequence_claims: {[c.claim_id for c in allocated.sequence_claims]}")
    print(f"  resolution_claims: {[c.claim_id for c in allocated.resolution_claims]}")
    print(f"  budgeted_word_counts: {allocated.budgeted_word_counts}")
    print(f"  derived_runtime_minutes: {allocated.derived_runtime_minutes}")


def _run(subject_id: int, thesis: str, dry_run: bool) -> int:
    with get_session() as session:
        if not dry_run:
            _require_backup()
            existing = session.exec(select(Episode).where(Episode.subject_id == subject_id)).first()
            if existing is not None:
                raise SetupAborted(
                    f"refusing to run: subject {subject_id} already has episode "
                    f"id={existing.id} -- not creating a second one without --dry-run"
                )
            _require_row_exists(session, VariationProfile, VARIATION_PROFILE_ID, "VariationProfile")
            _require_row_exists(session, SubtitleStyle, SUBTITLE_STYLE_ID, "SubtitleStyle")

        source_ids = _qualifying_source_ids(session, subject_id)
        print(f"qualifying sources (>=1 RESOLUTION claim): {source_ids}")
        if not source_ids:
            raise SetupAborted(
                f"refusing to run: subject {subject_id} has no source with a "
                f"RESOLUTION-tagged claim"
            )

        pool = _claim_pool(session, subject_id, source_ids)
        pool_ids = [c.id for c in pool]
        print(f"claim pool ({len(pool)} claims): {pool_ids}")

        thesis_bearing_ids = _thesis_bearing_claim_ids(pool)
        print(f"thesis-bearing ({len(thesis_bearing_ids)}): {sorted(thesis_bearing_ids)}")

        cold_open_claim_id = _cold_open_claim_id(pool)
        if cold_open_claim_id is None:
            raise SetupAborted(
                "refusing to run: no RESOLUTION-tagged claim in the pool to use as cold open"
            )
        print(f"cold_open_claim_id: {cold_open_claim_id}")

        episode = _build_episode(
            session, subject_id, thesis, pool, thesis_bearing_ids, cold_open_claim_id
        )
        assert episode.id is not None
        print(f"episode id={episode.id} flushed (not yet committed)")

        _report_allocation(episode.id, pool, thesis_bearing_ids, session)

        if dry_run:
            session.rollback()
            print()
            print("DRY RUN -- nothing written, session rolled back.")
        else:
            _check_foreign_keys(session, "pre-commit")
            session.commit()
            _check_foreign_keys(session, "post-commit")
            print()
            print(f"COMMITTED -- episode_id={episode.id}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject-id", type=int, required=True)
    parser.add_argument("--thesis", type=str, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        return _run(args.subject_id, args.thesis, args.dry_run)
    except SetupAborted as exc:
        print(f"ABORTED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
