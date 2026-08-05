"""packages/research/entity_extraction.py: known-entity context assembly
from founding EntityMatch rows, candidate validation, match-or-create
resolution, match_rationale presence/absence enforcement, duplicate-match
guarding, living=None on every automated write, and the
no-op-unless-forced re-extraction rule.

Uses a fake provider (packages.research.entity_provider.EntityExtractionProvider
is a Protocol precisely so tests never need a real Gemini call).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from packages.db.models import Entity, EntityMatch, Source
from packages.domain.enums import EntityRole, ImageRights, SourceTier
from packages.research.entity_extraction import (
    MAX_IDENTIFYING_SPAN_CHARS,
    extract_entities_for_source,
)
from packages.research.entity_provider import KnownEntity, ProposedEntity
from tests.factories import make_entity, make_entity_match, make_source, make_subject

SOURCE_TEXT = (
    "In March 1922, six people vanished from a small farmstead in Bavaria. "
    "Andreas Gruber, his wife, their widowed daughter, and her four children "
    "had not been seen for several days when a neighbor grew concerned and "
    "went to check on them. Investigators later determined the family had "
    "been killed."
)

VALID_SPAN = "Andreas Gruber"


class _FakeProvider:
    def __init__(self, entities: list[ProposedEntity]) -> None:
        self._entities = entities
        self.calls = 0
        self.last_known_entities: list[KnownEntity] | None = None

    async def extract_entities(
        self, source_text: str, known_entities: list[KnownEntity]
    ) -> list[ProposedEntity]:
        self.calls += 1
        self.last_known_entities = known_entities
        return self._entities


def _make_source(session: Session, subject_id: int, tmp_path: Path, **overrides: Any) -> Source:
    if "text_path" not in overrides:
        text_path = tmp_path / "source.txt"
        text_path.write_text(SOURCE_TEXT, encoding="utf-8")
        overrides["text_path"] = str(text_path)
    overrides.setdefault("tier", SourceTier.RETROSPECTIVE)
    overrides.setdefault("url", f"https://example.com/{overrides.get('title', 'article')}")
    source = make_source(subject_id, **overrides)
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def _valid_candidate(**overrides: Any) -> ProposedEntity:
    defaults: dict[str, Any] = dict(
        name="Andreas Gruber",
        role="victim",
        identifying_span=VALID_SPAN,
        matched_entity_id=None,
        match_rationale=None,
    )
    defaults.update(overrides)
    return ProposedEntity(**defaults)


def _id(row: Entity | Source) -> int:
    """Every persisted-and-refreshed row's id is real; narrows the
    id/None type once instead of an `assert row.id is not None` at every
    call site that needs to pass one as a plain int argument."""
    assert row.id is not None
    return row.id


def _persist_subject(session: Session, strategy_id: int) -> int:
    subject = make_subject(strategy_id)
    session.add(subject)
    session.commit()
    session.refresh(subject)
    assert subject.id is not None
    return subject.id


async def test_new_entity_is_persisted_with_located_span_and_no_rationale(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate()])

    result = await extract_entities_for_source(session, source, provider)

    assert len(result.entities) == 1
    entity = result.entities[0]
    assert entity.is_new is True
    assert entity.matched_entity_id is None
    assert entity.match_rationale is None
    assert entity.span_start == SOURCE_TEXT.find(VALID_SPAN)
    assert entity.span_end == entity.span_start + len(VALID_SPAN)
    assert entity.role == EntityRole.VICTIM

    persisted = session.get(Entity, entity.entity_id)
    assert persisted is not None
    assert persisted.living is None  # never touched by automated extraction
    assert persisted.adjudicated is False
    assert persisted.image_rights == ImageRights.NONE

    match = session.exec(
        select(EntityMatch).where(EntityMatch.entity_id == entity.entity_id)
    ).one()
    assert match.source_id == source.id
    assert match.identifying_span == VALID_SPAN
    assert match.match_rationale is None


async def test_known_entities_are_built_from_founding_match_not_most_recent(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    founding_source = _make_source(session, subject_id, tmp_path, title="founding")
    later_source = _make_source(session, subject_id, tmp_path, title="later")
    assert founding_source.id is not None
    assert later_source.id is not None
    founding_source_id = founding_source.id
    later_source_id = later_source.id

    entity = make_entity(subject_id, name="Andreas Gruber", role=EntityRole.VICTIM)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    assert entity.id is not None
    entity_id = entity.id

    founding_match = make_entity_match(
        entity_id, founding_source_id, identifying_span="the founding span"
    )
    session.add(founding_match)
    session.commit()
    # A second, later match for the same entity, from a different source --
    # the founding match (lower id) must still be what's used, not this one.
    later_match = make_entity_match(entity_id, later_source_id, identifying_span="a later span")
    session.add(later_match)
    session.commit()

    new_source = _make_source(session, subject_id, tmp_path, title="new")
    provider = _FakeProvider([])

    await extract_entities_for_source(session, new_source, provider)

    assert provider.last_known_entities is not None
    assert len(provider.last_known_entities) == 1
    known = provider.last_known_entities[0]
    assert known.entity_id == entity_id
    assert known.identifying_span == "the founding span"
    assert known.source_id == founding_source.id
    assert known.source_title == founding_source.title


async def test_hand_entered_entity_with_no_entity_match_is_excluded_from_known_context(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    hand_entered = make_entity(subject_id)  # no EntityMatch row -- seeded/hand-entered
    session.add(hand_entered)
    session.commit()

    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([])

    await extract_entities_for_source(session, source, provider)

    assert provider.last_known_entities == []


async def test_matched_candidate_is_linked_to_existing_entity_not_created_anew(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    founding_source = _make_source(session, subject_id, tmp_path, title="founding")
    entity = make_entity(subject_id, name="Andreas Gruber", role=EntityRole.VICTIM)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    assert entity.id is not None
    entity_id = entity.id
    session.add(make_entity_match(entity_id, _id(founding_source)))
    session.commit()

    new_source = _make_source(session, subject_id, tmp_path, title="new")
    provider = _FakeProvider(
        [
            _valid_candidate(
                matched_entity_id=entity_id,
                match_rationale="Same name and role as the known victim.",
            )
        ]
    )

    result = await extract_entities_for_source(session, new_source, provider)

    assert len(result.entities) == 1
    assert result.entities[0].is_new is False
    assert result.entities[0].entity_id == entity_id
    assert session.exec(select(Entity)).all() == [entity]  # no new Entity created

    match = session.exec(
        select(EntityMatch).where(
            EntityMatch.entity_id == entity_id, EntityMatch.source_id == new_source.id
        )
    ).one()
    assert match.match_rationale == "Same name and role as the known victim."


async def test_matched_entity_id_not_in_known_ids_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider(
        [_valid_candidate(matched_entity_id=999999, match_rationale="not a real id")]
    )

    result = await extract_entities_for_source(session, source, provider)

    assert result.entities == []
    assert result.rejected[0].reason == "invalid_matched_entity_id"
    assert session.exec(select(Entity)).all() == []


async def test_missing_match_rationale_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    founding_source = _make_source(session, subject_id, tmp_path, title="founding")
    entity = make_entity(subject_id)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    assert entity.id is not None
    entity_id = entity.id
    session.add(make_entity_match(entity_id, _id(founding_source)))
    session.commit()

    new_source = _make_source(session, subject_id, tmp_path, title="new")
    provider = _FakeProvider(
        [_valid_candidate(matched_entity_id=entity_id, match_rationale=None)]
    )

    result = await extract_entities_for_source(session, new_source, provider)

    assert result.entities == []
    assert result.rejected[0].reason == "missing_match_rationale"


async def test_unexpected_match_rationale_on_new_entity_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider(
        [_valid_candidate(matched_entity_id=None, match_rationale="there is nothing to explain")]
    )

    result = await extract_entities_for_source(session, source, provider)

    assert result.entities == []
    assert result.rejected[0].reason == "unexpected_match_rationale"
    assert session.exec(select(Entity)).all() == []


async def test_span_not_found_is_rejected_not_persisted(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider(
        [_valid_candidate(identifying_span="a name that never appears in the source")]
    )

    result = await extract_entities_for_source(session, source, provider)

    assert result.entities == []
    assert result.rejected[0].reason == "span_not_found"
    assert session.exec(select(Entity)).all() == []


async def test_span_too_long_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    long_text = "Andreas Gruber. " * 60  # comfortably over 800 chars
    assert len(long_text) > MAX_IDENTIFYING_SPAN_CHARS
    subject_id = _persist_subject(session, strategy_id)
    text_path = tmp_path / "long_source.txt"
    text_path.write_text(long_text, encoding="utf-8")
    source = _make_source(session, subject_id, tmp_path, text_path=str(text_path))
    provider = _FakeProvider([_valid_candidate(identifying_span=long_text)])

    result = await extract_entities_for_source(session, source, provider)

    assert result.entities == []
    assert result.rejected[0].reason == "span_too_long"


async def test_empty_name_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate(name="   ")])

    result = await extract_entities_for_source(session, source, provider)

    assert result.rejected[0].reason == "empty_name"


async def test_empty_span_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate(identifying_span="   ")])

    result = await extract_entities_for_source(session, source, provider)

    assert result.rejected[0].reason == "empty_span"


async def test_invalid_role_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate(role="not_a_real_role")])

    result = await extract_entities_for_source(session, source, provider)

    assert result.rejected[0].reason == "invalid_role"


async def test_duplicate_match_within_same_batch_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    founding_source = _make_source(session, subject_id, tmp_path, title="founding")
    entity = make_entity(subject_id)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    assert entity.id is not None
    entity_id = entity.id
    session.add(make_entity_match(entity_id, _id(founding_source)))
    session.commit()

    new_source = _make_source(session, subject_id, tmp_path, title="new")
    candidate = _valid_candidate(matched_entity_id=entity_id, match_rationale="same person")
    provider = _FakeProvider([candidate, candidate])  # two mentions, same source, same match

    result = await extract_entities_for_source(session, new_source, provider)

    assert len(result.entities) == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "duplicate_match_in_batch"
    matches = session.exec(
        select(EntityMatch).where(
            EntityMatch.entity_id == entity_id, EntityMatch.source_id == new_source.id
        )
    ).all()
    assert len(matches) == 1  # UniqueConstraint would have rejected a second


async def test_duplicate_match_against_a_prior_forced_batch_is_rejected(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    founding_source = _make_source(session, subject_id, tmp_path, title="founding")
    entity = make_entity(subject_id)
    session.add(entity)
    session.commit()
    session.refresh(entity)
    assert entity.id is not None
    entity_id = entity.id
    session.add(make_entity_match(entity_id, _id(founding_source)))
    session.commit()

    new_source = _make_source(session, subject_id, tmp_path, title="new")
    candidate = _valid_candidate(matched_entity_id=entity_id, match_rationale="same person")
    provider = _FakeProvider([candidate])
    await extract_entities_for_source(session, new_source, provider)

    # Forced re-run against the same source proposes the same match again.
    result = await extract_entities_for_source(session, new_source, provider, force=True)

    assert result.entities == []
    assert result.rejected[0].reason == "duplicate_match_in_batch"


async def test_dry_run_persists_nothing(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate()])

    result = await extract_entities_for_source(session, source, provider, dry_run=True)

    assert len(result.entities) == 1
    assert result.entities[0].entity_id is None
    assert session.exec(select(Entity)).all() == []
    assert session.exec(select(EntityMatch)).all() == []


async def test_reextraction_without_force_is_a_noop_and_skips_the_provider_call(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate()])
    await extract_entities_for_source(session, source, provider)
    assert provider.calls == 1

    result = await extract_entities_for_source(session, source, provider)

    assert result.skipped_already_extracted is True
    assert provider.calls == 1  # not called again
    assert len(session.exec(select(Entity)).all()) == 1


async def test_forced_reextraction_adds_a_second_batch_without_touching_the_first(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    source = _make_source(session, subject_id, tmp_path)
    provider = _FakeProvider([_valid_candidate()])
    first = await extract_entities_for_source(session, source, provider)
    first_entity_id = first.entities[0].entity_id

    second = await extract_entities_for_source(session, source, provider, force=True)

    assert second.skipped_already_extracted is False
    assert len(second.entities) == 1
    assert second.entities[0].entity_id != first_entity_id
    all_entities = session.exec(select(Entity)).all()
    assert len(all_entities) == 2
    assert session.get(Entity, first_entity_id) is not None  # untouched, not deleted
