from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from packages.db.models import (
    Channel,
    Claim,
    Entity,
    Episode,
    Source,
    Strategy,
    Subject,
    SubtitleStyle,
    VariationProfile,
)
from packages.domain.enums import (
    ClaimCategory,
    ClaimConfidence,
    ClaimType,
    ColdOpenStyle,
    EntityRole,
    EpisodeArchitecture,
    ImageRights,
    Platform,
    ResolutionStatus,
    SourceTier,
    ThumbnailComposition,
)
from packages.strategies.criminal_cases import SLUG as CRIMINAL_CASES_SLUG
from packages.strategies.criminal_cases.enums import CaseType


def make_strategy(**overrides: Any) -> Strategy:
    defaults: dict[str, Any] = dict(
        slug=CRIMINAL_CASES_SLUG,
        name="Criminal Cases",
        description="Well-documented criminal cases with primary-record sourcing.",
        subject_noun_singular="case",
        subject_noun_plural="cases",
        min_verified_sources=3,
        min_primary_records=1,
        min_distinct_domains=3,
        style_guide={},
        allowed_archive_providers=[],
    )
    defaults.update(overrides)
    return Strategy(**defaults)


def make_subject(strategy_id: int, **overrides: Any) -> Subject:
    defaults: dict[str, Any] = dict(
        strategy_id=strategy_id,
        slug="test-subject",
        title="Test Subject",
        attributes={"case_type": CaseType.HOMICIDE},
        event_year=1950,
        country="US",
        region=None,
        summary="A test subject.",
        resolution_status=ResolutionStatus.CONVICTED,
        living_persons_involved=False,
        risk_flags=[],
        documentation_score=4,
    )
    defaults.update(overrides)
    return Subject(**defaults)


def make_channel(strategy_id: int, **overrides: Any) -> Channel:
    defaults: dict[str, Any] = dict(
        strategy_id=strategy_id,
        platform=Platform.YOUTUBE,
        display_name="",
        external_account_id="",
        credentials_ref="",
        is_active=False,
    )
    defaults.update(overrides)
    return Channel(**defaults)


def make_source(subject_id: int, **overrides: Any) -> Source:
    # domain is derived from url by packages/db/listeners.py; not settable here.
    defaults: dict[str, Any] = dict(
        subject_id=subject_id,
        url="https://example.com/article",
        publisher="Example Publisher",
        title="An article",
        published_date=None,
        retrieved_at=datetime.now(UTC),
        tier=SourceTier.RETROSPECTIVE,
        text_path="/tmp/text.txt",
        text_sha256="0" * 64,
        word_count=500,
    )
    defaults.update(overrides)
    return Source(**defaults)


def make_claim(subject_id: int, **overrides: Any) -> Claim:
    # narratable defaults False -- packages/db/listeners.py rejects True at
    # creation unconditionally, see NarratableSourcingError.
    defaults: dict[str, Any] = dict(
        subject_id=subject_id,
        statement="A test claim.",
        category=ClaimCategory.EVENT,
        claim_type=ClaimType.FACT,
        confidence=ClaimConfidence.ESTABLISHED,
        contested_note=None,
        date_anchor=None,
        narratable=False,
    )
    defaults.update(overrides)
    return Claim(**defaults)


def make_entity(subject_id: int, **overrides: Any) -> Entity:
    defaults: dict[str, Any] = dict(
        subject_id=subject_id,
        name="Test Entity",
        role=EntityRole.WITNESS,
        living=False,
        adjudicated=False,
        image_rights=ImageRights.PUBLIC_DOMAIN,
    )
    defaults.update(overrides)
    return Entity(**defaults)


def make_subtitle_style(**overrides: Any) -> SubtitleStyle:
    defaults: dict[str, Any] = dict(
        name="Default",
        font_family="Arial",
        font_size=64,
        primary_colour="&H00FFFFFF",
        outline_colour="&H00000000",
        outline_width=3.0,
        shadow=1.0,
        alignment=2,
        margin_v=60,
        max_chars_per_line=42,
    )
    defaults.update(overrides)
    return SubtitleStyle(**defaults)


def make_variation_profile(
    strategy_id: int, subtitle_style_id: int, **overrides: Any
) -> VariationProfile:
    defaults: dict[str, Any] = dict(
        strategy_id=strategy_id,
        cold_open_style=ColdOpenStyle.SCENE_FIRST,
        act_count=4,
        narration_wpm=145,
        shot_duration_mean_s=6.0,
        shot_duration_sd_s=1.5,
        transition_set=["hard_cut"],
        music_present=False,
        music_intensity=0.0,
        subtitle_style_id=subtitle_style_id,
        thumbnail_composition=ThumbnailComposition.LOCATION_WIDE,
    )
    defaults.update(overrides)
    return VariationProfile(**defaults)


def make_episode(subject_id: int, variation_profile_id: int, **overrides: Any) -> Episode:
    # generation_fingerprint defaults None, not "" -- see Episode's
    # UniqueConstraint(subject_id, generation_fingerprint); NULL is exempt
    # from the constraint, "" would not be.
    defaults: dict[str, Any] = dict(
        subject_id=subject_id,
        variation_profile_id=variation_profile_id,
        thesis="A test thesis.",
        architecture=EpisodeArchitecture.CHRONOLOGICAL,
        generation_fingerprint=None,
    )
    defaults.update(overrides)
    return Episode(**defaults)
