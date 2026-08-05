"""Entity.living's evidence invariant -- see docs/SCHEMA.md's Entity section.

living may only move off None when living_evidence_source_id/living_evidence/
living_evidence_span_start/living_evidence_span_end are all present, the span
is actually located in that source's text, that source's tier is Tier A, and
that source has an EntityMatch row for this same entity. Enforced across
Entity.before_insert, Entity.before_update, and Source.before_update -- see
packages/db/listeners.py. Each failure mode is tested directly here, not just
asserted in prose, mirroring tests/test_claim_persistence.py's own posture
toward the narratable invariant.

Not yet collectible: these import LivingEvidenceError, which doesn't exist
until packages/db/listeners.py implements this invariant. Written first, as
the concrete spec for that implementation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlmodel import Session, select

from packages.db.listeners import LivingEvidenceError
from packages.db.models import Entity, EntityMatch, TimestampedModel
from packages.domain.enums import SourceTier
from tests.factories import make_entity, make_source, make_subject

# Duplicated from tests/test_claim_persistence.py rather than shared -- see
# that file's own version. Small enough that a shared helper module isn't
# worth it yet.


def _persist[T: TimestampedModel](session: Session, obj: T) -> int:
    session.add(obj)
    session.commit()
    session.refresh(obj)
    assert obj.id is not None
    return obj.id


def _make_tier_a_source_with_text(
    session: Session, subject_id: int, tmp_path: Path, text: str
) -> int:
    path = tmp_path / "source.txt"
    path.write_text(text, encoding="utf-8")
    return _persist(
        session,
        make_source(subject_id, tier=SourceTier.PRIMARY_RECORD, text_path=str(path)),
    )


# --------------------------------------------------------------------------
# Entity.before_insert -- living is never valid at creation (same FK-
# ordering reasoning as narratable=True at Claim creation)
# --------------------------------------------------------------------------


def test_entity_cannot_be_created_living(session: Session, strategy_id: int) -> None:
    subject_id = _persist(session, make_subject(strategy_id))

    with pytest.raises(LivingEvidenceError):
        session.add(make_entity(subject_id, living=False))
        session.commit()


# --------------------------------------------------------------------------
# Entity.before_update -- the four negative conditions, each isolated
# --------------------------------------------------------------------------


def test_entity_living_requires_evidence(session: Session, strategy_id: int) -> None:
    """No evidence at all -- the cheapest, most basic violation."""
    subject_id = _persist(session, make_subject(strategy_id))
    entity_id = _persist(session, make_entity(subject_id))

    entity = session.get(Entity, entity_id)
    assert entity is not None
    entity.living = False
    session.add(entity)
    with pytest.raises(LivingEvidenceError):
        session.commit()


def test_entity_living_rejects_non_tier_a_evidence(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """A complete, otherwise-valid evidence chain -- real located span, real
    EntityMatch -- fails on tier alone."""
    subject_id = _persist(session, make_subject(strategy_id))
    text = "Karl Gruber died in the spring of 1923, the parish register records."
    path = tmp_path / "source.txt"
    path.write_text(text, encoding="utf-8")
    source_id = _persist(
        session,
        make_source(subject_id, tier=SourceTier.RETROSPECTIVE, text_path=str(path)),
    )
    entity_id = _persist(session, make_entity(subject_id))
    session.add(
        EntityMatch(
            entity_id=entity_id,
            source_id=source_id,
            identifying_span="Karl Gruber",
            span_start=0,
            span_end=len("Karl Gruber"),
        )
    )
    session.commit()

    quote = "died in the spring of 1923"
    span_start = text.index(quote)
    entity = session.get(Entity, entity_id)
    assert entity is not None
    entity.living = False
    entity.living_evidence_source_id = source_id
    entity.living_evidence = quote
    entity.living_evidence_span_start = span_start
    entity.living_evidence_span_end = span_start + len(quote)
    session.add(entity)
    with pytest.raises(LivingEvidenceError):
        session.commit()


def test_entity_living_rejects_unlocatable_evidence(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """Tier A source, real EntityMatch -- fails because living_evidence
    isn't actually in the source's text (a fabricated or paraphrased
    quote)."""
    subject_id = _persist(session, make_subject(strategy_id))
    text = "Karl Gruber died in the spring of 1923, the parish register records."
    source_id = _make_tier_a_source_with_text(session, subject_id, tmp_path, text)
    entity_id = _persist(session, make_entity(subject_id))
    session.add(
        EntityMatch(
            entity_id=entity_id,
            source_id=source_id,
            identifying_span="Karl Gruber",
            span_start=0,
            span_end=len("Karl Gruber"),
        )
    )
    session.commit()

    fabricated = "confirmed alive and well as of 1990"
    entity = session.get(Entity, entity_id)
    assert entity is not None
    entity.living = True
    entity.living_evidence_source_id = source_id
    entity.living_evidence = fabricated
    entity.living_evidence_span_start = 0
    entity.living_evidence_span_end = len(fabricated)
    session.add(entity)
    with pytest.raises(LivingEvidenceError):
        session.commit()


def test_entity_living_requires_entity_match_for_source(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """Tier A source, real located span at the correct offsets -- fails
    because this source was never established to be about this entity at
    all (no EntityMatch row). This is the misattribution gap: a real,
    correctly-quoted death notice from a source that was never linked to
    this entity in the first place."""
    subject_id = _persist(session, make_subject(strategy_id))
    text = "Karl Gruber died in the spring of 1923, the parish register records."
    source_id = _make_tier_a_source_with_text(session, subject_id, tmp_path, text)
    entity_id = _persist(session, make_entity(subject_id))
    # Deliberately no EntityMatch row for (entity_id, source_id).

    quote = "died in the spring of 1923"
    span_start = text.index(quote)
    entity = session.get(Entity, entity_id)
    assert entity is not None
    entity.living = False
    entity.living_evidence_source_id = source_id
    entity.living_evidence = quote
    entity.living_evidence_span_start = span_start
    entity.living_evidence_span_end = span_start + len(quote)
    session.add(entity)
    with pytest.raises(LivingEvidenceError):
        session.commit()


# --------------------------------------------------------------------------
# The happy path -- proves the listener doesn't just always raise, and
# replaces the old test_entity_living_is_queryable in
# tests/test_claim_persistence.py, which constructed living=True/False
# directly at insert and would now fail under Entity.before_insert.
# --------------------------------------------------------------------------


def test_entity_living_can_be_set_with_full_evidence_and_is_queryable(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist(session, make_subject(strategy_id))
    text = "Karl Gruber died in the spring of 1923, the parish register records."
    source_id = _make_tier_a_source_with_text(session, subject_id, tmp_path, text)

    deceased_id = _persist(session, make_entity(subject_id, name="Deceased Witness"))
    living_id = _persist(session, make_entity(subject_id, name="Unreviewed Witness"))
    session.add(
        EntityMatch(
            entity_id=deceased_id,
            source_id=source_id,
            identifying_span="Karl Gruber",
            span_start=0,
            span_end=len("Karl Gruber"),
        )
    )
    session.commit()

    quote = "died in the spring of 1923"
    span_start = text.index(quote)
    deceased = session.get(Entity, deceased_id)
    assert deceased is not None
    deceased.living = False
    deceased.living_evidence_source_id = source_id
    deceased.living_evidence = quote
    deceased.living_evidence_span_start = span_start
    deceased.living_evidence_span_end = span_start + len(quote)
    session.add(deceased)
    session.commit()  # must not raise

    session.refresh(deceased)
    assert deceased.living is False

    # The second entity was never reviewed -- living stays None, not False,
    # and must not be mistaken for "confirmed not living" by a query that
    # only checks for False.
    unreviewed = session.get(Entity, living_id)
    assert unreviewed is not None
    assert unreviewed.living is None

    # Filtered in Python, not SQL: living != True is NULL-unsafe (SQL's
    # three-valued logic makes NULL != True evaluate to NULL, not true, so
    # the unreviewed row would silently vanish from a `!=` filter), and
    # the NULL-safe operator (is_not) needs SQLAlchemy's mypy plugin to
    # type-check, which this project doesn't have. Not worth adding a
    # plugin for one assertion in one test.
    all_entities = session.exec(select(Entity).where(Entity.subject_id == subject_id)).all()
    not_confirmed_living = {e.id for e in all_entities if e.living is not True}
    assert not_confirmed_living == {deceased_id, living_id}
