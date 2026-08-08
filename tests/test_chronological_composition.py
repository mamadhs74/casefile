"""packages/script/chronological_composition.py: compose_episode, step 3
wired into the chronological architecture's generator via the B option --
generate_script itself is untouched by this file (see
tests/test_script_chronological.py, unmodified). Covers the 2-4 call
count, recomputed actual_word_counts, which fields carry over unchanged,
and that a generate_script failure happens before any provider call.

Uses a local fake provider (packages.script.composition_provider.CompositionProvider
is a Protocol precisely so tests never need a real Gemini call) -- same
pattern as tests/test_composition.py's _FakeCompositionProvider and
tests/test_claim_extraction.py's _FakeProvider.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from packages.db.models import Claim, Episode, TimestampedModel
from packages.domain.enums import EpisodeArchitecture, Section, SourceTier
from packages.script.chronological import ThesisBearingCountError
from packages.script.chronological_composition import compose_episode
from packages.script.composition_provider import ClaimForComposition, ComposedSection
from tests.factories import (
    make_claim,
    make_claim_source,
    make_episode,
    make_episode_claim,
    make_source,
    make_subject,
    make_subtitle_style,
    make_variation_profile,
)


class _FakeCompositionProvider:
    def __init__(self, text: str | None = None) -> None:
        self._text = text
        self.call_args: list[tuple[list[ClaimForComposition], str, int]] = []

    async def compose_section(
        self, claims: list[ClaimForComposition], thesis: str, word_budget: int
    ) -> ComposedSection:
        self.call_args.append((list(claims), thesis, word_budget))
        text = self._text if self._text is not None else f"composed section {len(self.call_args)}"
        return ComposedSection(text=text)


def _persist[T: TimestampedModel](session: Session, obj: T) -> int:
    session.add(obj)
    session.commit()
    session.refresh(obj)
    assert obj.id is not None
    return obj.id


def _build_episode_with_claims(
    session: Session,
    strategy_id: int,
    *,
    thesis: str | None,
    architecture: EpisodeArchitecture | None,
    claim_specs: list[tuple[str, bool, Section | None]],
) -> tuple[int, list[int]]:
    """Same shape as tests/test_script_chronological.py's own copy --
    claim_specs is (date_anchor, thesis_bearing, section) per claim."""
    subject_id = _persist(session, make_subject(strategy_id))
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    subtitle_style_id = _persist(session, make_subtitle_style())
    variation_profile_id = _persist(
        session, make_variation_profile(strategy_id, subtitle_style_id)
    )
    episode_id = _persist(
        session,
        make_episode(subject_id, variation_profile_id, thesis=thesis, architecture=architecture),
    )

    claim_ids: list[int] = []
    for date_anchor, thesis_bearing, section in claim_specs:
        claim_id = _persist(
            session, make_claim(subject_id, date_anchor=date_anchor, section=section)
        )
        session.add(make_claim_source(claim_id, source_id))
        session.commit()

        claim = session.get(Claim, claim_id)
        assert claim is not None
        claim.narratable = True
        session.add(claim)
        session.commit()

        session.add(make_episode_claim(episode_id, claim_id, thesis_bearing=thesis_bearing))
        session.commit()
        claim_ids.append(claim_id)

    return episode_id, claim_ids


def _set_cold_open(session: Session, episode_id: int, claim_id: int) -> None:
    episode = session.get(Episode, episode_id)
    assert episode is not None
    episode.cold_open_claim_id = claim_id
    session.add(episode)
    session.commit()


def _statement(session: Session, claim_id: int) -> str:
    claim = session.get(Claim, claim_id)
    assert claim is not None
    return claim.statement


async def test_compose_episode_calls_only_sequence_and_return_when_ground_and_resolution_empty(
    session: Session, strategy_id: int
) -> None:
    """5 untagged claims -- Ground and Resolution never receive a claim,
    so they must not be called at all. Floor of the 2-4 range."""
    episode_id, claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="A real thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[
            ("1893-06-01", True, None),
            ("1893-06-02", True, None),
            ("1893-06-03", True, None),
            ("1893-06-04", True, None),
            ("1893-06-05", True, None),
        ],
    )
    _set_cold_open(session, episode_id, claim_ids[0])
    provider = _FakeCompositionProvider()

    script = await compose_episode(session, episode_id, provider, min_claim_count=5)

    assert len(provider.call_args) == 2
    assert script.ground == ""
    assert script.resolution == ""


async def test_compose_episode_calls_all_four_when_ground_and_resolution_nonempty(
    session: Session, strategy_id: int
) -> None:
    """One GROUND, one RESOLUTION, three untagged (cold open among them)
    -- the ceiling of the 2-4 range."""
    episode_id, claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="A real thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[
            ("1893-06-01", True, Section.GROUND),
            ("1893-06-20", True, Section.RESOLUTION),
            ("1893-06-05", True, None),
            ("1893-06-15", True, None),
            ("1893-06-09", True, None),
        ],
    )
    _set_cold_open(session, episode_id, claim_ids[2])
    provider = _FakeCompositionProvider()

    script = await compose_episode(session, episode_id, provider, min_claim_count=5)

    assert len(provider.call_args) == 4
    assert script.ground != ""
    assert script.resolution != ""


async def test_compose_episode_recomputes_actual_word_counts_from_composed_text(
    session: Session, strategy_id: int
) -> None:
    """rule 4: actual_word_counts must reflect the *composed* text, not
    generate_script's concatenation-era counts -- the fake returns a
    fixed 3-word string regardless of input, so a passing assertion here
    can only mean the count was recomputed, not carried over."""
    episode_id, claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="A real thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[
            ("1893-06-01", True, Section.GROUND),
            ("1893-06-20", True, Section.RESOLUTION),
            ("1893-06-05", True, None),
            ("1893-06-15", True, None),
            ("1893-06-09", True, None),
        ],
    )
    _set_cold_open(session, episode_id, claim_ids[2])
    provider = _FakeCompositionProvider(text="Exactly three words.")

    script = await compose_episode(session, episode_id, provider, min_claim_count=5)

    assert script.actual_word_counts.ground == 3
    assert script.actual_word_counts.resolution == 3
    assert script.actual_word_counts.sequence == 3
    assert script.actual_word_counts.return_ == 3
    # Cold Open and Thesis got no call -- their counts are untouched from
    # whatever generate_script's own concatenation already computed, not
    # coincidentally re-equal to the fake's fixed 3-word output.
    assert script.actual_word_counts.cold_open == len(_statement(session, claim_ids[2]).split())
    assert script.actual_word_counts.thesis == len("A real thesis.".split())


async def test_compose_episode_preserves_fields_composition_does_not_touch(
    session: Session, strategy_id: int
) -> None:
    """cold_open, thesis, budgeted_word_counts, untagged_claim_count, and
    the *_claims allocation lists all come from generate_script's own
    allocation and must carry over unchanged -- composition revises text
    and actual counts, nothing else."""
    episode_id, claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="A real thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[
            ("1893-06-01", True, Section.GROUND),
            ("1893-06-20", True, Section.RESOLUTION),
            ("1893-06-05", True, None),
            ("1893-06-15", True, None),
            ("1893-06-09", True, None),
        ],
    )
    _set_cold_open(session, episode_id, claim_ids[2])
    provider = _FakeCompositionProvider()

    script = await compose_episode(session, episode_id, provider, min_claim_count=5)

    assert script.cold_open == _statement(session, claim_ids[2])
    assert script.thesis == "A real thesis."
    assert script.untagged_claim_count == 3
    assert script.budgeted_word_counts.sequence > 0
    assert len(script.ground_claims) == 1
    assert len(script.resolution_claims) == 1
    assert len(script.sequence_claims) == 3


async def test_compose_episode_propagates_generate_script_failures_before_any_call(
    session: Session, strategy_id: int
) -> None:
    """generate_script's own checks run first -- a rule-6 failure must
    raise before the provider is ever touched, so no quota is spent on an
    episode that was never going to render."""
    episode_id, _claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="A real thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[
            ("1893-06-01", False, None),
            ("1893-06-02", False, None),
            ("1893-06-03", False, None),
        ],
    )
    provider = _FakeCompositionProvider()

    with pytest.raises(ThesisBearingCountError):
        await compose_episode(session, episode_id, provider, min_claim_count=3)

    assert provider.call_args == []
