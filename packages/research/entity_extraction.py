"""Turns a persisted Source's text into Entity/EntityMatch rows --
docs/SCHEMA.md's Entity extraction section. Provider-agnostic: talks only
to packages.research.entity_provider.EntityExtractionProvider, never a
specific SDK -- same reasoning as claim_extraction.py.

Every Entity this creates gets living=None here, in addition to
packages/db/listeners.py's own enforcement (Entity.before_insert rejects
any other value outright) -- belt-and-suspenders, same posture as
narratable=False in claim extraction. Evidencing living is always a
later, separate write this module never makes.

Order, all before any persistence:

1. Skip entirely if this Source already has any linked EntityMatch,
   unless force=True -- re-extraction is not deterministic, and a prior
   match may already back evidenced living_evidence or be cited via
   ClaimEntity. force=True does not delete or merge anything; it adds a
   second batch of candidate Entity/EntityMatch rows alongside the first,
   for a human to reconcile -- entity resolution is relational, so a
   second batch can disagree with the first about entity *boundaries*,
   not just about which rows exist -- see docs/SCHEMA.md.
2. Assemble the subject's known-entity context: one KnownEntity per
   existing Entity that has at least one EntityMatch, built from that
   entity's *founding* match (the lowest-id EntityMatch row for that
   entity_id, not the most recent) -- see docs/SCHEMA.md and
   entity_provider.py's KnownEntity docstring for why. An Entity with no
   EntityMatch at all (hand-entered or seeded) has no founding match to
   build one from and is excluded from this context entirely -- a
   confirmed gap, not silently patched over: the model has no way to know
   such an entity exists, and could propose a duplicate for the same real
   person.
3. Ask the provider for proposed entities.
4. For each proposed entity, in order:
   a. Reject if name or identifying_span is blank.
   b. Reject if identifying_span is not found in the source's text (same
      whitespace-normalized locate_span() ClaimSource.quoted_span and
      Entity.living_evidence both use).
   c. Reject if the located span exceeds MAX_IDENTIFYING_SPAN_CHARS.
   d. Reject if role isn't a recognized EntityRole value. The provider's
      own structured-output schema should make this unreachable; this
      check is defensive, not load-bearing, same posture as claim_type
      elsewhere.
   e. Reject if matched_entity_id is not None and isn't one of the ids
      actually sent to the provider in known_entities this call.
   f. Reject if matched_entity_id is not None and match_rationale is
      blank/None ("missing_match_rationale"), or matched_entity_id is
      None and match_rationale is present ("unexpected_match_rationale").
   g. For a candidate matching an existing entity: reject if
      (matched_entity_id, source.id) already has an EntityMatch row --
      either from an earlier candidate in this same batch, or a prior
      batch -- rather than let UniqueConstraint(entity_id, source_id)
      raise IntegrityError. Two *new* candidates (matched_entity_id=None)
      for the same real person mentioned twice in one source can't hit
      this constraint (each gets its own new Entity row before the
      EntityMatch insert), so within-source coreference for new entities
      is not checked here -- it's an assumption about the provider's own
      prompt, not something this module can validate after the fact.
5. Persist Entity (only when matched_entity_id is None) + exactly one
   EntityMatch per surviving candidate, whether the mention resolves to a
   new Entity or an existing one -- every source's contribution to an
   entity's identity is independently inspectable, founding mention
   included. dry_run=True runs every step above but skips persistence,
   returning what would have been created.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session, select

from packages.db.models import Entity, EntityMatch, Source
from packages.domain.enums import EntityRole, ImageRights
from packages.domain.spans import locate_span
from packages.research.entity_provider import EntityExtractionProvider, KnownEntity, ProposedEntity

MAX_IDENTIFYING_SPAN_CHARS = 800


@dataclass(frozen=True)
class RejectedEntity:
    """identifying_span is what the model attempted, kept even on
    rejection -- same reasoning as claim_extraction.py's RejectedClaim."""

    name: str
    identifying_span: str
    reason: str
    # "empty_name" | "empty_span" | "span_not_found" | "span_too_long" |
    # "invalid_role" | "invalid_matched_entity_id" |
    # "missing_match_rationale" | "unexpected_match_rationale" |
    # "duplicate_match_in_batch"


@dataclass(frozen=True)
class ExtractedEntity:
    """One entity mention this run created (or matched), or would have in
    dry-run mode. entity_id is None exactly when dry_run=True and this
    mention is new -- nothing was persisted. is_new distinguishes "a new
    Entity was created for this mention" from "this mention was matched
    to an existing one" -- matched_entity_id alone can't, since it's
    always None on a founding mention regardless of dry_run."""

    entity_id: int | None
    is_new: bool
    name: str
    role: EntityRole
    identifying_span: str
    span_start: int
    span_end: int
    matched_entity_id: int | None
    match_rationale: str | None


@dataclass(frozen=True)
class EntityExtractionResult:
    source_id: int
    skipped_already_extracted: bool = False
    entities: list[ExtractedEntity] = field(default_factory=list)
    rejected: list[RejectedEntity] = field(default_factory=list)


@dataclass(frozen=True)
class _ValidatedCandidate:
    role: EntityRole
    span_start: int
    span_end: int
    identifying_span: str  # source_text[span_start:span_end] -- the real
    # matched text, not the model's normalized version. Keeps
    # identifying_span consistent with the offsets it's stored alongside.
    matched_entity_id: int | None
    match_rationale: str | None


async def extract_entities_for_source(
    session: Session,
    source: Source,
    provider: EntityExtractionProvider,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> EntityExtractionResult:
    assert source.id is not None
    source_id = source.id

    if not force and _has_existing_entity_matches(session, source_id):
        return EntityExtractionResult(source_id=source_id, skipped_already_extracted=True)

    source_text = Path(source.text_path).read_text(encoding="utf-8")
    known_entities = known_entities_for_subject(session, source.subject_id)
    known_ids = {ke.entity_id for ke in known_entities}

    proposed = await provider.extract_entities(source_text, known_entities)

    extracted: list[ExtractedEntity] = []
    rejected: list[RejectedEntity] = []
    matched_this_batch: set[int] = set()  # entity_ids already matched to
    # this source within this same run -- see step 4g above.

    for candidate in proposed:
        outcome = _validate(candidate, source_text, known_ids)
        if isinstance(outcome, str):
            rejected.append(
                RejectedEntity(
                    name=candidate.name,
                    identifying_span=candidate.identifying_span,
                    reason=outcome,
                )
            )
            continue

        if outcome.matched_entity_id is not None:
            target_id = outcome.matched_entity_id
            if target_id in matched_this_batch or _entity_match_exists(
                session, target_id, source_id
            ):
                rejected.append(
                    RejectedEntity(
                        name=candidate.name,
                        identifying_span=outcome.identifying_span,
                        reason="duplicate_match_in_batch",
                    )
                )
                continue
            matched_this_batch.add(target_id)

        is_new = outcome.matched_entity_id is None
        entity_id: int | None = outcome.matched_entity_id

        if not dry_run:
            if is_new:
                entity = Entity(
                    subject_id=source.subject_id,
                    name=candidate.name,
                    role=outcome.role,
                    living=None,  # hardcoded, never derived here -- see module docstring
                    adjudicated=False,
                    image_rights=ImageRights.NONE,
                )
                session.add(entity)
                session.commit()
                session.refresh(entity)
                assert entity.id is not None
                entity_id = entity.id

            assert entity_id is not None
            session.add(
                EntityMatch(
                    entity_id=entity_id,
                    source_id=source_id,
                    identifying_span=outcome.identifying_span,
                    span_start=outcome.span_start,
                    span_end=outcome.span_end,
                    match_rationale=outcome.match_rationale,
                )
            )
            session.commit()

        extracted.append(
            ExtractedEntity(
                entity_id=entity_id,
                is_new=is_new,
                name=candidate.name,
                role=outcome.role,
                identifying_span=outcome.identifying_span,
                span_start=outcome.span_start,
                span_end=outcome.span_end,
                matched_entity_id=outcome.matched_entity_id,
                match_rationale=outcome.match_rationale,
            )
        )

    return EntityExtractionResult(source_id=source_id, entities=extracted, rejected=rejected)


def _has_existing_entity_matches(session: Session, source_id: int) -> bool:
    return (
        session.exec(select(EntityMatch).where(EntityMatch.source_id == source_id)).first()
        is not None
    )


def _entity_match_exists(session: Session, entity_id: int, source_id: int) -> bool:
    return (
        session.exec(
            select(EntityMatch).where(
                EntityMatch.entity_id == entity_id, EntityMatch.source_id == source_id
            )
        ).first()
        is not None
    )


def known_entities_for_subject(session: Session, subject_id: int) -> list[KnownEntity]:
    """Public (not module-private) because scripts/extract_entities.py's
    --dry-run request preview needs the exact same known-entity context a
    real call would build, and duplicating this query there would drift
    from this one -- same reasoning as locate_span() living in
    packages.domain.spans instead of two independent implementations."""
    entities = session.exec(select(Entity).where(Entity.subject_id == subject_id)).all()

    known: list[KnownEntity] = []
    for entity in entities:
        assert entity.id is not None
        founding = session.exec(
            select(EntityMatch)
            .where(EntityMatch.entity_id == entity.id)
            .order_by(EntityMatch.id)  # type: ignore[arg-type]  # always set once persisted
        ).first()
        if founding is None:
            # Hand-entered/seeded entity with no EntityMatch -- excluded,
            # see module docstring's step 2.
            continue

        founding_source = session.get(Source, founding.source_id)
        assert founding_source is not None  # FK guarantees this resolves

        known.append(
            KnownEntity(
                entity_id=entity.id,
                name=entity.name,
                role=entity.role.value,
                identifying_span=founding.identifying_span,
                source_id=founding.source_id,
                source_title=founding_source.title,
            )
        )
    return known


def _validate(
    candidate: ProposedEntity, source_text: str, known_ids: set[int]
) -> _ValidatedCandidate | str:
    """Returns the validated span/enum/match values, or a short rejection-
    reason string identifying which check failed."""
    if not candidate.name.strip():
        return "empty_name"
    if not candidate.identifying_span.strip():
        return "empty_span"

    span = locate_span(candidate.identifying_span, source_text)
    if span is None:
        return "span_not_found"
    span_start, span_end = span

    if span_end - span_start > MAX_IDENTIFYING_SPAN_CHARS:
        return "span_too_long"

    try:
        role = EntityRole(candidate.role)
    except ValueError:
        return "invalid_role"

    matched_entity_id = candidate.matched_entity_id
    if matched_entity_id is not None and matched_entity_id not in known_ids:
        return "invalid_matched_entity_id"

    rationale = candidate.match_rationale
    if matched_entity_id is not None and not (rationale or "").strip():
        return "missing_match_rationale"
    if matched_entity_id is None and rationale is not None:
        return "unexpected_match_rationale"

    return _ValidatedCandidate(
        role=role,
        span_start=span_start,
        span_end=span_end,
        identifying_span=source_text[span_start:span_end],
        matched_entity_id=matched_entity_id,
        match_rationale=rationale,
    )
