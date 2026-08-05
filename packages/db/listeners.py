"""Persistence-layer enforcement of computed fields and write-time invariants.

Two distinct things live here, both because no code path -- API, script,
direct session use -- may be able to slip past them:

- Computed fields a caller must not be able to hand-set are recomputed in
  before_insert/before_update listeners, unconditionally (Subject's scoring,
  Source's domain).
- Invariants a write must not be able to violate raise on before_insert/
  before_update/before_delete instead of silently correcting anything --
  see NarratableSourcingError and NonNarratableClaimError below. Correcting
  narratable to a value the caller didn't ask for would look like their
  write succeeded when it didn't; rejecting it is the honest failure mode.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import event, func
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper
from sqlmodel import select

import packages.strategies.criminal_cases  # noqa: F401  registers the criminal-cases strategy
from packages.db.models import Claim, ClaimSource, EpisodeClaim, Source, Strategy, Subject
from packages.domain.enums import TIER_A_SOURCE_TIERS
from packages.domain.urls import derive_domain
from packages.research.dispatch import UnknownStrategyError, score_subject, validate_attributes


def _resolve_strategy_slug(connection: Connection, strategy_id: int) -> str:
    query = select(Strategy.slug).where(Strategy.id == strategy_id)
    slug = connection.execute(query).scalar_one_or_none()
    if slug is None:
        raise UnknownStrategyError(strategy_id)
    return slug


@event.listens_for(Subject, "before_insert")
@event.listens_for(Subject, "before_update")
def _validate_and_score_subject(
    mapper: Mapper[Any], connection: Connection, target: Subject
) -> None:
    """Resolves target.strategy_id to that strategy's code (never trusting a
    slug the caller might pass elsewhere) and applies it unconditionally:
    attributes get validated + normalized, and monetization_tier/legal_risk/
    eligibility_notes get recomputed. Mirrors the guarantee the old
    Case listener made -- a raw session write cannot bypass either.
    """
    strategy_slug = _resolve_strategy_slug(connection, target.strategy_id)

    target.attributes = validate_attributes(strategy_slug, target.attributes)

    result = score_subject(target, strategy_slug)
    target.monetization_tier = result.tier
    target.legal_risk = result.legal_risk
    target.eligibility_notes = result.notes


@event.listens_for(Source, "before_insert")
@event.listens_for(Source, "before_update")
def _derive_source_domain(mapper: Mapper[Any], connection: Connection, target: Source) -> None:
    target.domain = derive_domain(target.url)


# --------------------------------------------------------------------------
# docs/SOURCING.md's core invariant: a narratable Claim's sourcing must be
# exclusively Tier A. Five touchpoints across three tables, because there
# are five different writes that could otherwise put a narratable Claim
# into a state where that's no longer true.
# --------------------------------------------------------------------------


class NarratableSourcingError(Exception):
    """A write would leave (or try to create) a narratable Claim without
    sourcing that is entirely Tier A."""


class NonNarratableClaimError(Exception):
    """An EpisodeClaim would select a Claim that isn't narratable."""


def _claim_source_tiers(connection: Connection, claim_id: int) -> list[Any]:
    query = (
        select(Source.tier)
        .select_from(ClaimSource, Source)
        .where(ClaimSource.claim_id == claim_id, Source.id == ClaimSource.source_id)
    )
    return list(connection.execute(query).scalars())


@event.listens_for(Claim, "before_insert")
def _reject_narratable_at_creation(
    mapper: Mapper[Any], connection: Connection, target: Claim
) -> None:
    """A Claim cannot cite a source before it exists -- ClaimSource.claim_id
    requires the Claim to already have a row. So narratable=True is never
    valid at creation; this isn't really a check, it falls out of FK
    ordering."""
    if target.narratable:
        raise NarratableSourcingError(
            "a claim cannot be created as narratable -- it has no sources yet"
        )


@event.listens_for(Claim, "before_update")
def _validate_narratable_claim_sourcing(
    mapper: Mapper[Any], connection: Connection, target: Claim
) -> None:
    if not target.narratable:
        return
    if target.id is None:
        # before_update -- the row should already exist and have an id. If
        # it doesn't, there's nothing to validate sourcing against, so this
        # can't be allowed to proceed as if it were fine.
        raise NarratableSourcingError(
            "cannot validate narratable sourcing for a claim with no id"
        )
    tiers = _claim_source_tiers(connection, target.id)
    if not tiers or any(tier not in TIER_A_SOURCE_TIERS for tier in tiers):
        raise NarratableSourcingError(
            f"claim {target.id} cannot be narratable: it needs at least one source, "
            "and every linked source must be Tier A"
        )


@event.listens_for(ClaimSource, "before_insert")
def _validate_new_claim_source(
    mapper: Mapper[Any], connection: Connection, target: ClaimSource
) -> None:
    """Attaching a weak source to an already-narratable claim would degrade
    it silently -- reject the attach instead."""
    narratable = connection.execute(
        select(Claim.narratable).where(Claim.id == target.claim_id)
    ).scalar_one_or_none()
    if not narratable:
        return
    tier = connection.execute(
        select(Source.tier).where(Source.id == target.source_id)
    ).scalar_one_or_none()
    if tier not in TIER_A_SOURCE_TIERS:
        raise NarratableSourcingError(
            f"cannot attach a {tier} source to narratable claim {target.claim_id}"
        )


@event.listens_for(ClaimSource, "before_delete")
def _guard_last_source_removal(
    mapper: Mapper[Any], connection: Connection, target: ClaimSource
) -> None:
    """Removing a narratable claim's only source would leave it vacuously
    "all sources are Tier A" (there being none) while violating the actual
    requirement -- at least one Tier A source, not just no bad ones."""
    narratable = connection.execute(
        select(Claim.narratable).where(Claim.id == target.claim_id)
    ).scalar_one_or_none()
    if not narratable:
        return
    remaining = connection.execute(
        select(func.count())
        .select_from(ClaimSource)
        .where(ClaimSource.claim_id == target.claim_id)
    ).scalar_one()
    if remaining <= 1:
        raise NarratableSourcingError(
            f"cannot remove the last source from narratable claim {target.claim_id} "
            "-- mark it not narratable first"
        )


@event.listens_for(Source, "before_update")
def _guard_cited_source_tier_downgrade(
    mapper: Mapper[Any], connection: Connection, target: Source
) -> None:
    """A source's tier can't be edited out from under a narratable claim
    that already cites it -- closes the gap where a claim would silently
    become invalid without anything about the claim itself changing."""
    if target.tier in TIER_A_SOURCE_TIERS:
        return
    cited_by_narratable = connection.execute(
        select(func.count())
        .select_from(ClaimSource, Claim)
        .where(
            ClaimSource.source_id == target.id,
            Claim.id == ClaimSource.claim_id,
            Claim.narratable,
        )
    ).scalar_one()
    if cited_by_narratable > 0:
        raise NarratableSourcingError(
            f"cannot change source {target.id} to tier {target.tier} -- "
            "it is cited by at least one narratable claim"
        )


@event.listens_for(EpisodeClaim, "before_insert")
def _reject_non_narratable_episode_claim(
    mapper: Mapper[Any], connection: Connection, target: EpisodeClaim
) -> None:
    narratable = connection.execute(
        select(Claim.narratable).where(Claim.id == target.claim_id)
    ).scalar_one_or_none()
    if not narratable:
        raise NonNarratableClaimError(
            f"claim {target.claim_id} is not narratable and cannot be selected into an episode"
        )
