"""scripts/create_episode.py: the one-episode-per-subject guard, and
--allow-additional's deliberate override of it.

Two things monkeypatched in every test here, both load-bearing, not
incidental cleanup:

1. _require_backup() checks a real file on disk (data/casefile.db.bak),
   unrelated to the in-memory test session -- patched to a no-op so
   these tests are hermetic and don't depend on repo state outside the
   test DB.
2. create_episode_for_subject calls packages.db.session.get_session()
   internally, which is NOT the test's own `session` fixture -- it's a
   separate, lazily-created, process-global engine that defaults to
   the REAL on-disk data/casefile.db (packages/db/session.py's own
   DEFAULT_DB_PATH) unless CASEFILE_DB_PATH is set. Left unpatched,
   these tests would silently read from and write to the real
   production database instead of the in-memory test one -- confirmed
   by running this file once without the patch below, which raised
   SetupAborted from a query that saw none of this test's own fixture
   data, because it was querying an entirely different database.
   Patched to return a fresh Session bound to the *same engine* as the
   test's own `session` fixture (not the same Session object -- that
   would close on the function's own `with ... as session:` exit and
   break this test's later assertions) so both sides see one shared
   in-memory database.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session, select

import scripts.create_episode as create_episode_module
from packages.db.models import Claim, Episode
from packages.domain.enums import Section, SourceTier
from scripts.create_episode import SetupAborted, create_episode_for_subject
from tests.factories import (
    make_claim,
    make_claim_source,
    make_episode,
    make_source,
    make_subject,
    make_subtitle_style,
    make_variation_profile,
)


@pytest.fixture(autouse=True)
def _hermetic_create_episode(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(create_episode_module, "_require_backup", lambda: None)
    engine = session.get_bind()
    monkeypatch.setattr(create_episode_module, "get_session", lambda: Session(engine))


def _persist_subject(session: Session, strategy_id: int) -> int:
    subject = make_subject(strategy_id)
    session.add(subject)
    session.commit()
    session.refresh(subject)
    assert subject.id is not None
    return subject.id


def _persist_variation_profile_and_subtitle_style(session: Session, strategy_id: int) -> None:
    """Must land at id=1 each -- create_episode.py hardcodes
    VARIATION_PROFILE_ID = SUBTITLE_STYLE_ID = 1. Each test's session
    fixture is a fresh in-memory DB, so the first row inserted into
    each of these two tables gets id=1, same as the real DB's own
    first-ever setup (module docstring)."""
    subtitle_style = make_subtitle_style()
    session.add(subtitle_style)
    session.commit()
    session.refresh(subtitle_style)
    assert subtitle_style.id == 1

    variation_profile = make_variation_profile(strategy_id, subtitle_style.id)
    session.add(variation_profile)
    session.commit()
    session.refresh(variation_profile)
    assert variation_profile.id == 1


def _persist_qualifying_pool(session: Session, subject_id: int) -> None:
    """One source, 5 RESOLUTION-tagged claims -- satisfies
    _qualifying_source_ids (>=1 RESOLUTION claim), rule 6's 5-10
    thesis-bearing floor (all 5 become thesis_bearing via GROUND/
    RESOLUTION tagging), and cold-open selection (max RESOLUTION id).
    min_claim_count is len(pool) at call time, so rule 7's 40-claim
    floor never applies here -- see module docstring."""
    # Tier A -- _build_episode flips narratable=True on every pool claim,
    # and packages/db/listeners.py's NarratableSourcingError rejects that
    # unless every linked source is Tier A.
    source = make_source(subject_id, tier=SourceTier.PRIMARY_RECORD)
    session.add(source)
    session.commit()
    session.refresh(source)
    assert source.id is not None

    for _ in range(5):
        claim = make_claim(subject_id, section=Section.RESOLUTION)
        session.add(claim)
        session.commit()
        session.refresh(claim)
        assert claim.id is not None
        session.add(make_claim_source(claim.id, source.id))
    session.commit()


async def test_guard_blocks_a_second_episode_without_the_flag(
    session: Session, strategy_id: int
) -> None:
    """Unchanged behavior: without --allow-additional, a subject that
    already has an episode refuses a second one."""
    subject_id = _persist_subject(session, strategy_id)
    existing = make_episode(subject_id, variation_profile_id=1)
    session.add(existing)
    session.commit()
    session.refresh(existing)

    with pytest.raises(SetupAborted, match="already has episode"):
        create_episode_for_subject(subject_id, "A new thesis.")

    all_episodes = session.exec(select(Episode).where(Episode.subject_id == subject_id)).all()
    assert len(all_episodes) == 1
    assert all_episodes[0].id == existing.id


async def test_allow_additional_permits_a_second_episode(
    session: Session, strategy_id: int
) -> None:
    """--allow-additional overrides only the one-episode-per-subject
    guard -- every other check (VariationProfile/SubtitleStyle exist,
    a qualifying source, rule 6's thesis-bearing floor, cold-open
    validation) still runs and must still pass."""
    subject_id = _persist_subject(session, strategy_id)
    _persist_variation_profile_and_subtitle_style(session, strategy_id)
    existing = make_episode(subject_id, variation_profile_id=1)
    session.add(existing)
    session.commit()
    session.refresh(existing)
    assert existing.id is not None

    _persist_qualifying_pool(session, subject_id)

    new_episode_id = create_episode_for_subject(
        subject_id, "A second thesis.", allow_additional=True
    )

    assert new_episode_id != existing.id
    all_episodes = session.exec(select(Episode).where(Episode.subject_id == subject_id)).all()
    assert len(all_episodes) == 2
    assert {e.id for e in all_episodes} == {existing.id, new_episode_id}

    new_episode = session.get(Episode, new_episode_id)
    assert new_episode is not None
    assert new_episode.thesis == "A second thesis."

    pool_claims = session.exec(select(Claim).where(Claim.subject_id == subject_id)).all()
    assert all(c.narratable for c in pool_claims)  # flipped by _build_episode
