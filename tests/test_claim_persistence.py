"""docs/SOURCING.md's core invariant: a narratable Claim's sourcing must be
exclusively Tier A. This is enforced across five listener touchpoints on
three tables (Claim, ClaimSource, Source) -- see packages/db/listeners.py --
because there are five different writes that could otherwise put a
narratable Claim into a state where that's no longer true. Each is tested
here directly, not just the happy path.

Also covers the EpisodeClaim narratable gate and Episode's exact-duplicate
generation_fingerprint constraint.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from packages.db.listeners import NarratableSourcingError, NonNarratableClaimError
from packages.db.models import (
    Claim,
    ClaimEntity,
    EpisodeClaim,
    Source,
    TimestampedModel,
)
from packages.domain.enums import SourceTier
from tests.factories import (
    make_claim,
    make_claim_source,
    make_entity,
    make_episode,
    make_episode_claim,
    make_source,
    make_subject,
    make_subtitle_style,
    make_variation_profile,
)


def _persist[T: TimestampedModel](session: Session, obj: T) -> int:
    session.add(obj)
    session.commit()
    session.refresh(obj)
    assert obj.id is not None
    return obj.id


def _make_variation_profile_id(session: Session, strategy_id: int) -> int:
    subtitle_style_id = _persist(session, make_subtitle_style())
    profile = make_variation_profile(strategy_id, subtitle_style_id)
    session.add(profile)
    session.commit()
    session.refresh(profile)
    assert profile.id is not None
    return profile.id


# --------------------------------------------------------------------------
# Claim.before_insert -- narratable=True is never valid at creation
# --------------------------------------------------------------------------


def test_claim_cannot_be_created_narratable(session: Session, strategy_id: int) -> None:
    subject_id = _persist(session, make_subject(strategy_id))

    with pytest.raises(NarratableSourcingError):
        session.add(make_claim(subject_id, narratable=True))
        session.commit()


# --------------------------------------------------------------------------
# Claim.before_update -- flipping narratable requires >=1 source, all Tier A
# --------------------------------------------------------------------------


def test_claim_becomes_narratable_with_a_tier_a_source(session: Session, strategy_id: int) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    session.add(make_claim_source(claim_id, source_id))
    session.commit()

    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)
    session.commit()

    session.refresh(claim)
    assert claim.narratable is True


def test_claim_cannot_become_narratable_with_zero_sources(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))

    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)

    with pytest.raises(NarratableSourcingError):
        session.commit()


def test_claim_cannot_become_narratable_with_a_tier_b_source(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.RETROSPECTIVE))
    session.add(make_claim_source(claim_id, source_id))
    session.commit()

    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)

    with pytest.raises(NarratableSourcingError):
        session.commit()


def test_claim_with_one_tier_b_and_one_tier_a_source_cannot_be_narratable(
    session: Session, strategy_id: int
) -> None:
    """Mixed sourcing fails closed -- every linked source must be Tier A,
    not just at least one."""
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    tier_a_id = _persist(
        session, make_source(subject_id, url="https://a.gov/1", tier=SourceTier.PRIMARY_RECORD)
    )
    tier_b_id = _persist(
        session, make_source(subject_id, url="https://b.com/1", tier=SourceTier.BOOK)
    )
    session.add(make_claim_source(claim_id, tier_a_id))
    session.add(make_claim_source(claim_id, tier_b_id))
    session.commit()

    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)

    with pytest.raises(NarratableSourcingError):
        session.commit()


# --------------------------------------------------------------------------
# ClaimSource.before_insert -- can't attach a weak source to a claim that's
# already narratable
# --------------------------------------------------------------------------


def test_cannot_attach_tier_b_source_to_already_narratable_claim(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    tier_a_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    session.add(make_claim_source(claim_id, tier_a_id))
    session.commit()
    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)
    session.commit()

    tier_b_id = _persist(
        session, make_source(subject_id, url="https://b.com/2", tier=SourceTier.UNVERIFIED)
    )

    with pytest.raises(NarratableSourcingError):
        session.add(make_claim_source(claim_id, tier_b_id))
        session.commit()


def test_can_attach_another_tier_a_source_to_narratable_claim(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    first_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    session.add(make_claim_source(claim_id, first_id))
    session.commit()
    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)
    session.commit()

    second_id = _persist(
        session, make_source(subject_id, url="https://c.gov/1", tier=SourceTier.CONTEMPORANEOUS)
    )
    session.add(make_claim_source(claim_id, second_id))
    session.commit()  # must not raise


# --------------------------------------------------------------------------
# ClaimSource.before_delete -- can't strip a narratable claim's last source
# --------------------------------------------------------------------------


def test_cannot_remove_last_source_from_narratable_claim(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    link = make_claim_source(claim_id, source_id)
    session.add(link)
    session.commit()
    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)
    session.commit()

    session.delete(link)
    with pytest.raises(NarratableSourcingError):
        session.commit()


def test_can_remove_a_non_last_source_from_narratable_claim(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    first_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    second_id = _persist(
        session, make_source(subject_id, url="https://c.gov/1", tier=SourceTier.CONTEMPORANEOUS)
    )
    first_link = make_claim_source(claim_id, first_id)
    session.add(first_link)
    session.add(make_claim_source(claim_id, second_id))
    session.commit()
    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)
    session.commit()

    session.delete(first_link)
    session.commit()  # must not raise


# --------------------------------------------------------------------------
# Source.before_update -- can't downgrade a tier out from under a
# narratable claim
# --------------------------------------------------------------------------


def test_cannot_downgrade_tier_of_source_cited_by_narratable_claim(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    session.add(make_claim_source(claim_id, source_id))
    session.commit()
    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)
    session.commit()

    source = session.get(Source, source_id)
    assert source is not None
    source.tier = SourceTier.UNVERIFIED
    session.add(source)

    with pytest.raises(NarratableSourcingError):
        session.commit()


def test_can_change_tier_of_source_not_cited_by_narratable_claim(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))

    source = session.get(Source, source_id)
    assert source is not None
    source.tier = SourceTier.UNVERIFIED
    session.add(source)
    session.commit()  # must not raise -- nothing narratable cites it


# --------------------------------------------------------------------------
# EpisodeClaim.before_insert -- narratable gate one hop downstream
# --------------------------------------------------------------------------


def test_episode_claim_rejects_non_narratable_claim(session: Session, strategy_id: int) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    variation_profile_id = _make_variation_profile_id(session, strategy_id)
    episode_id = _persist(session, make_episode(subject_id, variation_profile_id))

    with pytest.raises(NonNarratableClaimError):
        session.add(EpisodeClaim(episode_id=episode_id, claim_id=claim_id, position=0))
        session.commit()


def test_episode_claim_accepts_narratable_claim(session: Session, strategy_id: int) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    session.add(make_claim_source(claim_id, source_id))
    session.commit()
    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)
    session.commit()

    variation_profile_id = _make_variation_profile_id(session, strategy_id)
    episode_id = _persist(session, make_episode(subject_id, variation_profile_id))

    session.add(EpisodeClaim(episode_id=episode_id, claim_id=claim_id, position=0))
    session.commit()  # must not raise


# --------------------------------------------------------------------------
# EpisodeClaim.thesis_bearing -- docs/ARCHITECTURES.md sec 4's thesis
# mechanism, a deliberate human write, same shape as Claim.narratable
# --------------------------------------------------------------------------


def test_episode_claim_thesis_bearing_defaults_false(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    session.add(make_claim_source(claim_id, source_id))
    session.commit()
    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)
    session.commit()

    variation_profile_id = _make_variation_profile_id(session, strategy_id)
    episode_id = _persist(session, make_episode(subject_id, variation_profile_id))
    episode_claim_id = _persist(session, make_episode_claim(episode_id, claim_id))

    episode_claim = session.get(EpisodeClaim, episode_claim_id)
    assert episode_claim is not None
    assert episode_claim.thesis_bearing is False


def test_episode_claim_thesis_bearing_set_true_persists(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    session.add(make_claim_source(claim_id, source_id))
    session.commit()
    claim = session.get(Claim, claim_id)
    assert claim is not None
    claim.narratable = True
    session.add(claim)
    session.commit()

    variation_profile_id = _make_variation_profile_id(session, strategy_id)
    episode_id = _persist(session, make_episode(subject_id, variation_profile_id))
    episode_claim_id = _persist(session, make_episode_claim(episode_id, claim_id))

    episode_claim = session.get(EpisodeClaim, episode_claim_id)
    assert episode_claim is not None
    episode_claim.thesis_bearing = True
    session.add(episode_claim)
    session.commit()

    # Expire and re-fetch rather than trust the same in-memory object --
    # this proves the value round-tripped through the database, not just
    # that the Python attribute held what we set on it.
    session.expire(episode_claim)
    reloaded = session.get(EpisodeClaim, episode_claim_id)
    assert reloaded is not None
    assert reloaded.thesis_bearing is True


# --------------------------------------------------------------------------
# Episode.generation_fingerprint -- exact-duplicate floor
# --------------------------------------------------------------------------


def test_duplicate_generation_fingerprint_on_same_subject_is_rejected(
    session: Session, strategy_id: int
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    variation_profile_id = _make_variation_profile_id(session, strategy_id)
    session.add(
        make_episode(subject_id, variation_profile_id, generation_fingerprint="abc123")
    )
    session.commit()

    session.add(
        make_episode(subject_id, variation_profile_id, generation_fingerprint="abc123")
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_null_generation_fingerprint_allows_multiple_episodes_per_subject(
    session: Session, strategy_id: int
) -> None:
    """generation_fingerprint defaults to None, not "" -- multiple
    not-yet-fingerprinted episodes for the same subject must coexist."""
    subject_id = _persist(session, make_subject(strategy_id))
    variation_profile_id = _make_variation_profile_id(session, strategy_id)
    session.add(make_episode(subject_id, variation_profile_id, generation_fingerprint=None))
    session.commit()

    session.add(make_episode(subject_id, variation_profile_id, generation_fingerprint=None))
    session.commit()  # must not raise


# Entity.living's evidence invariant (Entity.before_insert/before_update,
# Source.before_update) moved to tests/test_entity_persistence.py -- it's
# its own concern, not a Claim one, and the old version here constructed
# living=True/False directly at insert, which the new invariant rejects.


def test_duplicate_claim_entity_link_is_rejected(session: Session, strategy_id: int) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    claim_id = _persist(session, make_claim(subject_id))
    entity_id = _persist(session, make_entity(subject_id))

    session.add(ClaimEntity(claim_id=claim_id, entity_id=entity_id))
    session.commit()

    session.add(ClaimEntity(claim_id=claim_id, entity_id=entity_id))
    with pytest.raises(IntegrityError):
        session.commit()
