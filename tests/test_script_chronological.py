"""packages/script/chronological.py step 2: the six-section structure.
Covers episode/render-gate/profile preconditions, the per-claim narratable
re-check, rules 6 and 7, cold-open validation (all four failure modes), and
the success path -- section allocation, the untagged-claim report, and
rule 4's word-count report.
"""

from __future__ import annotations

import pytest
from sqlmodel import Session

from packages.db.models import Claim, Episode, TimestampedModel
from packages.domain.enums import EpisodeArchitecture, Section, SourceTier
from packages.script.chronological import (
    ClaimNotNarratableError,
    ColdOpenClaimNotFoundError,
    ColdOpenClaimNotInEpisodeError,
    ColdOpenClaimNotThesisBearingError,
    EpisodeNotFoundError,
    EpisodeNotRenderableError,
    InsufficientClaimCountError,
    NoColdOpenClaimError,
    ThesisBearingCountError,
    VariationProfileNotFoundError,
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
    claim_specs: list[tuple[str, bool, Section | None]],
) -> tuple[int, list[int]]:
    """claim_specs is (date_anchor, thesis_bearing, section) per claim.
    Builds one shared Tier A source, flips each claim narratable through
    the normal ORM path (Claim.before_update fires), and adds each to a
    fresh Episode's EpisodeClaim set (EpisodeClaim.before_insert fires).
    Returns (episode_id, claim_ids) in claim_specs order. Does not set
    cold_open_claim_id -- callers that need one set it themselves via
    _set_cold_open, same as any other post-build attribute set."""
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


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


def test_generate_script_success_path(session: Session, strategy_id: int) -> None:
    """5 claims, all thesis-bearing: one GROUND, one RESOLUTION, three
    untagged (Sequence). Cold open is one of the untagged three."""
    episode_id, claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="The investigation moved faster than the record admits.",
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

    script = generate_script(session, episode_id, min_claim_count=5)

    assert script.ground == "A test claim."
    assert script.resolution == "A test claim."
    assert script.cold_open == "A test claim."
    assert script.thesis == "The investigation moved faster than the record admits."
    assert script.return_ == script.thesis
    assert script.untagged_claim_count == 3

    # Sequence holds the three untagged claims (including the cold-open
    # one), sorted by date_anchor.
    assert script.sequence.count("A test claim.") == 3

    # Rule 4's report exists and is derived from narration_wpm (145
    # default), not a hardcoded 150 -- exact values aren't asserted here,
    # just that a real, positive budget was computed.
    assert script.budgeted_word_counts.sequence > 0
    assert script.actual_word_counts.ground == 3  # "A test claim." = 3 words

    # cold_open + ground + resolution + 3 sequence (the cold-open claim
    # appears in both cold_open and sequence, by design -- rule 2).
    assert script.text.count("A test claim.") == 6
    assert "The investigation moved faster" in script.text


def test_generate_script_ground_is_empty_when_no_claims_tagged_ground(
    session: Session, strategy_id: int
) -> None:
    """docs/ARCHITECTURES.md sec 3.3's fallback: no genuine setting
    material is expected, not an error. Ground emits an empty string;
    those claims' words are simply never in Ground's actual count."""
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

    script = generate_script(session, episode_id, min_claim_count=5)

    assert script.ground == ""
    assert script.actual_word_counts.ground == 0
    assert script.untagged_claim_count == 5


def test_generate_script_cold_open_claim_excluded_from_its_own_section_tag(
    session: Session, strategy_id: int
) -> None:
    """A claim tagged GROUND that is also the cold open must still land
    in exactly Cold Open and Sequence (rule 2), never also in Ground --
    the module's own resolution of a case ARCHITECTURES.md leaves
    implicit."""
    episode_id, claim_ids = _build_episode_with_claims(
        session,
        strategy_id,
        thesis="A real thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        claim_specs=[
            ("1893-06-01", True, Section.GROUND),
            ("1893-06-02", True, None),
            ("1893-06-03", True, None),
            ("1893-06-04", True, None),
            ("1893-06-05", True, None),
        ],
    )
    ground_tagged_claim_id = claim_ids[0]
    _set_cold_open(session, episode_id, ground_tagged_claim_id)

    script = generate_script(session, episode_id, min_claim_count=5)

    assert script.ground == ""
    assert script.cold_open == "A test claim."
    # The 4 untagged claims plus the GROUND-tagged cold-open claim,
    # diverted into Sequence instead of Ground.
    assert script.sequence.count("A test claim.") == 5


# ---------------------------------------------------------------------------
# Preconditions before section allocation
# ---------------------------------------------------------------------------


def test_generate_script_raises_when_episode_not_found(session: Session) -> None:
    with pytest.raises(EpisodeNotFoundError):
        generate_script(session, 999_999_999)


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


def test_generate_script_raises_when_variation_profile_missing(
    session: Session, strategy_id: int
) -> None:
    """Episode.variation_profile_id is NOT NULL but, like every FK here,
    unenforced at runtime -- rule 4's budget needs narration_wpm, so this
    has to be checked explicitly rather than crash confusingly."""
    subject_id = _persist(session, make_subject(strategy_id))
    episode_id = _persist(
        session,
        make_episode(
            subject_id,
            999_999_999,
            thesis="A real thesis.",
            architecture=EpisodeArchitecture.CHRONOLOGICAL,
        ),
    )

    with pytest.raises(VariationProfileNotFoundError):
        generate_script(session, episode_id, min_claim_count=0)


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
            ("1893-06-01", True, None),
            ("1893-06-02", True, None),
            ("1893-06-03", True, None),
            ("1893-06-04", True, None),
            ("1893-06-05", True, None),
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


def test_generate_script_raises_when_thesis_bearing_count_out_of_range(
    session: Session, strategy_id: int
) -> None:
    """Rule 6: 0 thesis-bearing claims, need 5-10. No cold_open_claim_id
    is set here -- this must fail on rule 6 before cold-open validation
    is ever reached, which is exactly why cold-open validation runs
    after rules 6/7 in generate_script."""
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

    with pytest.raises(ThesisBearingCountError):
        generate_script(session, episode_id, min_claim_count=3)


def test_generate_script_raises_when_claim_count_below_minimum(
    session: Session, strategy_id: int
) -> None:
    """Rule 7: 5 claims (enough to clear rule 6's floor) against an
    injected min_claim_count of 10 -- proves the override actually gates
    the production check rather than being decorative. No
    cold_open_claim_id needed -- rule 7 fails before cold-open validation."""
    episode_id, _claim_ids = _build_episode_with_claims(
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

    with pytest.raises(InsufficientClaimCountError):
        generate_script(session, episode_id, min_claim_count=10)


# ---------------------------------------------------------------------------
# Cold-open validation -- all four failure modes
# ---------------------------------------------------------------------------


def test_generate_script_raises_when_no_cold_open_claim_set(
    session: Session, strategy_id: int
) -> None:
    episode_id, _claim_ids = _build_episode_with_claims(
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

    with pytest.raises(NoColdOpenClaimError):
        generate_script(session, episode_id, min_claim_count=5)


def test_generate_script_raises_when_cold_open_claim_does_not_exist(
    session: Session, strategy_id: int
) -> None:
    episode_id, _claim_ids = _build_episode_with_claims(
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
    _set_cold_open(session, episode_id, 999_999_999)

    with pytest.raises(ColdOpenClaimNotFoundError):
        generate_script(session, episode_id, min_claim_count=5)


def test_generate_script_raises_when_cold_open_claim_not_in_episode(
    session: Session, strategy_id: int
) -> None:
    episode_id, _claim_ids = _build_episode_with_claims(
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
    # A real claim that exists, but was never added to this episode.
    other_subject_id = _persist(session, make_subject(strategy_id, slug="other-subject"))
    outside_claim_id = _persist(session, make_claim(other_subject_id))
    _set_cold_open(session, episode_id, outside_claim_id)

    with pytest.raises(ColdOpenClaimNotInEpisodeError):
        generate_script(session, episode_id, min_claim_count=5)


def test_generate_script_raises_when_cold_open_claim_not_thesis_bearing(
    session: Session, strategy_id: int
) -> None:
    """6 claims: 5 thesis-bearing (satisfies rule 6 exactly), 1 not.
    Pointing cold_open_claim_id at the 6th must fail even though it's a
    real claim in this episode's own set."""
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
            ("1893-06-06", False, None),
        ],
    )
    non_thesis_bearing_claim_id = claim_ids[5]
    _set_cold_open(session, episode_id, non_thesis_bearing_claim_id)

    with pytest.raises(ColdOpenClaimNotThesisBearingError):
        generate_script(session, episode_id, min_claim_count=6)
