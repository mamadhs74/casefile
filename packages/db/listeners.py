"""Persistence-layer enforcement of computed fields.

Values a caller must not be able to hand-set are recomputed in before_insert
and before_update listeners, unconditionally, so no code path -- API, script,
direct session use -- can slip past them.
"""

from __future__ import annotations

from typing import Any

import tldextract
from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapper
from sqlmodel import select

import packages.strategies.criminal_cases  # noqa: F401  registers the criminal-cases strategy
from packages.db.models import Source, Strategy, Subject
from packages.research.dispatch import UnknownStrategyError, score_subject, validate_attributes

# suffix_list_urls=() disables tldextract's live fetch of the Public Suffix
# List, so domain derivation never makes a network call and is deterministic
# in tests and CI -- it uses the snapshot bundled with the package.
_extract = tldextract.TLDExtract(suffix_list_urls=())


def _derive_domain(url: str) -> str:
    extracted = _extract(url)
    if extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}".lower()
    return extracted.domain.lower()


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
    target.domain = _derive_domain(target.url)
