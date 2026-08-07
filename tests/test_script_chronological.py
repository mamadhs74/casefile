"""packages/script/chronological.py step 1: episode_id in, the render gate
(rule 8 / docs/SCHEMA.md finding #13), and rules 6 and 7 as preconditions.
Output is still flat concatenation -- covered here as the success path,
not as its own concern; the six-section structure is step 2.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from packages.db.models import Claim, TimestampedModel
from packages.domain.enums import EpisodeArchitecture, SourceTier
from packages.script.chronological import (
    ClaimNotNarratableError,
    EpisodeNotRenderableError,
    InsufficientClaimCountError,
    ThesisBearingCountError,
    generate_script,
)
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
    claim_specs: list[tuple[str, bool]],
) -> tuple[int, list[int]]:
    """claim_specs is (date_anchor, thesis_bearing) per claim. Builds one
    shared Tier A source, flips each claim narratable through the normal
    ORM path (Claim.before_update fires), and adds each to a fresh
    Episode's EpisodeClaim set (EpisodeClaim.before_insert fires). Returns
    (episode_id, claim_ids) in claim_specs order."""
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
    for date_anchor, thesis_bearing in claim_specs:
        claim_id = _persist(session, make_claim(subject_id, date_anchor=date_anchor))
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


def test_generate_script_success_path(session: Session, strategy_id: int) -> None:
    """5 claims, all thesis-bearing, min_claim_count overridden to 5 --
    cheap fixture, same shape the real 40-claim floor would exercise."""
    episode_id, _claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="The investigation moved faster than the record admits.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[
            ("1893-06-05", True),
            ("1893-06-01", True),
            ("1893-06-20", True),
            ("1893-06-15", True),
            ("1893-06-09", True),
        ],
    )

    text = generate_script(session, episode_id, min_claim_count=5)

    lines = text.split("\n")
    assert len(lines) == 5
    # Sorted by date_anchor ascending regardless of insertion order.
    assert lines == [
        "A test claim.",
        "A test claim.",
        "A test claim.",
        "A test claim.",
        "A test claim.",
    ]


@pytest.mark.parametrize(
    "thesis, architecture",
    [
        ("", EpisodeArchitecture.CHRONOLOGICAL),
        ("A real thesis.", None),
    ],
)
def test_generate_script_raises_when_not_renderable(
    session: Session,
    strategy_id: int,
    thesis: str,
    architecture: EpisodeArchitecture | None,
) -> None:
    """Rule 8 / finding #13: empty thesis or null architecture, either
    one, blocks generation before any claim is even queried."""
    episode_id, _claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis=thesis,
        architecture=architecture,
        claim_specs=[],
    )

    with pytest.raises(EpisodeNotRenderableError):
        generate_script(session, episode_id, min_claim_count=0)


def test_generate_script_raises_when_thesis_bearing_count_out_of_range(
    session: Session, strategy_id: int
) -> None:
    """Rule 6: 0 thesis-bearing claims, need 5-10."""
    episode_id, _claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="A real thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[("1893-06-01", False), ("1893-06-02", False), ("1893-06-03", False)],
    )

    with pytest.raises(ThesisBearingCountError):
        generate_script(session, episode_id, min_claim_count=3)


def test_generate_script_raises_when_claim_count_below_minimum(
    session: Session, strategy_id: int
) -> None:
    """Rule 7: 5 claims (enough to clear rule 6's floor) against an
    injected min_claim_count of 10 -- proves the override actually gates
    the production check rather than being decorative."""
    episode_id, _claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="A real thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[
            ("1893-06-01", True),
            ("1893-06-02", True),
            ("1893-06-03", True),
            ("1893-06-04", True),
            ("1893-06-05", True),
        ],
    )

    with pytest.raises(InsufficientClaimCountError):
        generate_script(session, episode_id, min_claim_count=10)


def test_generate_script_raises_when_claim_narratable_degraded_after_insertion(
    session: Session, strategy_id: int
) -> None:
    """The gap the module docstring names: EpisodeClaim.before_insert only
    checks narratable once, at insert time. Flipping it back to False
    afterward has no listener guarding it at all -- Claim.before_update
    only validates a flip TO True. This proves the degraded claim doesn't
    silently reach output."""
    episode_id, claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="A real thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[
            ("1893-06-01", True),
            ("1893-06-02", True),
            ("1893-06-03", True),
            ("1893-06-04", True),
            ("1893-06-05", True),
        ],
    )
    degraded_claim_id = claim_ids[0]

    claim = session.get(Claim, degraded_claim_id)
    assert claim is not None
    claim.narratable = False
    session.add(claim)
    session.commit()  # must not raise -- no listener guards this direction

    with pytest.raises(ClaimNotNarratableError) as exc_info:
        generate_script(session, episode_id, min_claim_count=5)

    assert exc_info.value.claim_id == degraded_claim_id
