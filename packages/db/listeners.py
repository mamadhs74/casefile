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

from pathlib import Path
from typing import Any

from sqlalchemy import event, func
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper
from sqlmodel import select

import packages.strategies.criminal_cases  # noqa: F401  registers the criminal-cases strategy
import packages.strategies.film_tv_news  # noqa: F401  registers the film-tv-news strategy
from packages.db.models import (
    Claim,
    ClaimSource,
    Entity,
    EntityMatch,
    EpisodeClaim,
    Source,
    Strategy,
    Subject,
)
from packages.domain.enums import TIER_A_SOURCE_TIERS
from packages.domain.spans import locate_span
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


# --------------------------------------------------------------------------
# docs/SCHEMA.md's Entity.living evidence invariant, backing R8: living may
# only move off None when it's backed by a located, Tier A, entity-matched
# span. Three touchpoints across two tables, same shape as the narratable
# invariant above and for the same reason -- three different writes could
# otherwise leave a living determination unsupported by the evidence it
# claims to have.
#
# A consequence worth stating plainly: Entity.before_insert rejects any
# non-None living outright (an EntityMatch row can't reference an entity
# that doesn't have an id yet -- same FK-ordering reasoning as
# narratable=True at Claim creation, above). So creating an Entity and
# evidencing its living status are always two separate writes; there is no
# single write that creates an Entity with living already set.
#
# Same trust boundary as everywhere else in this file, worth restating here
# specifically: these fire on ORM flush only. A bulk UPDATE issued through
# session.exec(update(Entity)...), or raw SQL against the .db file,
# bypasses all three -- and this is already true of every narratable
# touchpoint above, not a new limitation introduced here.
# --------------------------------------------------------------------------


class LivingEvidenceError(Exception):
    """A write would leave (or try to create) a non-None Entity.living
    without evidence satisfying every condition in docs/SCHEMA.md's
    living-evidence invariant: all four evidence fields present, the cited
    source Tier A, an EntityMatch row linking that source to this entity,
    and living_evidence actually located at the stated offsets."""


def _source_tier_and_text_path(connection: Connection, source_id: int) -> Any:
    """One query for both fields the living-evidence check needs from the
    cited source -- avoids a second round trip to re-fetch text_path after
    checking tier. Returns None if source_id doesn't resolve."""
    query = select(Source.tier, Source.text_path).where(Source.id == source_id)
    return connection.execute(query).first()


@event.listens_for(Entity, "before_insert")
def _reject_living_at_creation(
    mapper: Mapper[Any], connection: Connection, target: Entity
) -> None:
    """An Entity cannot have an EntityMatch row before it exists --
    EntityMatch.entity_id requires the Entity to already have an id. So
    living being anything but None is never valid at creation; this isn't
    really a check, it falls out of FK ordering, same as
    _reject_narratable_at_creation above. Every Entity is created with
    living=None; evidencing it is always a later, separate update."""
    if target.living is not None:
        raise LivingEvidenceError(
            "an entity cannot be created with living set -- it has no "
            "EntityMatch rows yet to evidence it"
        )


@event.listens_for(Entity, "before_update")
def _validate_living_evidence(
    mapper: Mapper[Any], connection: Connection, target: Entity
) -> None:
    """Cheapest checks first, file I/O last. Verifies the caller-supplied
    living_evidence_span_start/_end rather than recomputing them -- a wrong
    offset alongside a real quote is a caller error worth surfacing, not
    silently correcting (see this module's own docstring)."""
    if target.living is None:
        return

    if (
        target.living_evidence_source_id is None
        or target.living_evidence is None
        or target.living_evidence_span_start is None
        or target.living_evidence_span_end is None
    ):
        raise LivingEvidenceError(
            f"entity {target.id} cannot set living without all four "
            "living_evidence fields present"
        )

    resolved = _source_tier_and_text_path(connection, target.living_evidence_source_id)
    if resolved is None:
        raise LivingEvidenceError(
            f"entity {target.id} cites living_evidence_source_id "
            f"{target.living_evidence_source_id}, which does not resolve to a source"
        )
    tier, text_path = resolved

    if tier not in TIER_A_SOURCE_TIERS:
        raise LivingEvidenceError(
            f"entity {target.id} cannot set living from a {tier} source -- "
            "living_evidence_source_id must be Tier A"
        )

    matched = connection.execute(
        select(func.count())
        .select_from(EntityMatch)
        .where(
            EntityMatch.entity_id == target.id,
            EntityMatch.source_id == target.living_evidence_source_id,
        )
    ).scalar_one()
    if matched == 0:
        raise LivingEvidenceError(
            f"entity {target.id} cannot cite source {target.living_evidence_source_id} "
            "as living_evidence_source_id -- no EntityMatch row establishes that "
            "source is about this entity"
        )

    try:
        source_text = Path(text_path).read_text(encoding="utf-8")
    except OSError as exc:
        raise LivingEvidenceError(
            f"entity {target.id}: could not read living_evidence_source_id "
            f"{target.living_evidence_source_id}'s text at {text_path!r}: {exc}"
        ) from exc

    located = locate_span(target.living_evidence, source_text)
    if located is None or located != (
        target.living_evidence_span_start,
        target.living_evidence_span_end,
    ):
        raise LivingEvidenceError(
            f"entity {target.id}: living_evidence is not located at the stated "
            "offsets in its source's text"
        )


@event.listens_for(Source, "before_update")
def _guard_living_evidence_source_tier_downgrade(
    mapper: Mapper[Any], connection: Connection, target: Source
) -> None:
    """A source cited as living_evidence_source_id can't have its tier
    edited out from under that evidence -- mirror of
    _guard_cited_source_tier_downgrade above, a separate function because
    it's a separate concern (Entity.living, not Claim.narratable), not
    merged into that one. Filters on living_evidence_source_id alone, not
    also on living IS NOT NULL: this guard shouldn't depend on a separate
    invariant already holding to do its job -- if an Entity somehow carries
    an evidence source with living=None, the downgrade is still blocked."""
    if target.tier in TIER_A_SOURCE_TIERS:
        return
    cited = connection.execute(
        select(func.count())
        .select_from(Entity)
        .where(Entity.living_evidence_source_id == target.id)
    ).scalar_one()
    if cited > 0:
        raise LivingEvidenceError(
            f"cannot change source {target.id} to tier {target.tier} -- it is "
            "cited as living_evidence_source_id by at least one entity"
        )
