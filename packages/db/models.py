"""SQLModel table definitions for casefile.

Mirrors docs/SCHEMA.md exactly. Every table gets id/created_at/updated_at via
`TimestampedModel` unless the schema doc notes otherwise (it doesn't, here).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON as SAJSON
from sqlalchemy import Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampedModel(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class CaseType(StrEnum):
    HOMICIDE = "homicide"
    DISAPPEARANCE = "disappearance"
    UNEXPLAINED_EVENT = "unexplained_event"
    HISTORICAL_HORROR = "historical_horror"
    MARITIME = "maritime"
    DISASTER = "disaster"
    INSTITUTIONAL_ABUSE = "institutional_abuse"


class ResolutionStatus(StrEnum):
    CONVICTED = "convicted"
    ACQUITTED = "acquitted"
    UNSOLVED = "unsolved"
    OFFICIALLY_RULED = "officially_ruled"
    DISPUTED = "disputed"


class RiskFlag(StrEnum):
    CHILD_VICTIM = "child_victim"
    SEXUAL_VIOLENCE = "sexual_violence"
    GRAPHIC_INJURY_CENTRAL = "graphic_injury_central"
    SUICIDE_CENTRAL = "suicide_central"
    ONGOING_LITIGATION = "ongoing_litigation"
    NAMED_LIVING_SUSPECT = "named_living_suspect"
    RECENT_EVENT = "recent_event"
    POLITICAL_VIOLENCE = "political_violence"
    HATE_MOTIVATED = "hate_motivated"


class MonetizationTier(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"


class LegalRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CaseStatus(StrEnum):
    CANDIDATE = "candidate"
    RESEARCHING = "researching"
    READY = "ready"
    IN_PRODUCTION = "in_production"
    PUBLISHED = "published"
    REJECTED = "rejected"


class SourceTier(StrEnum):
    PRIMARY_RECORD = "primary_record"
    CONTEMPORANEOUS = "contemporaneous"
    RETROSPECTIVE = "retrospective"
    BOOK = "book"
    REFERENCE = "reference"
    UNVERIFIED = "unverified"


class FactType(StrEnum):
    EVENT = "event"
    PERSON = "person"
    LOCATION = "location"
    TIMELINE = "timeline"
    EVIDENCE = "evidence"
    LEGAL_OUTCOME = "legal_outcome"
    AFTERMATH = "aftermath"


class PipelineStage(StrEnum):
    CREATED = "created"
    RESEARCHING = "researching"
    FACTS_RECONCILED = "facts_reconciled"
    SCRIPTED = "scripted"
    AWAITING_GATE_A = "awaiting_gate_a"
    SHOT_LIST = "shot_list"
    VISUALS = "visuals"
    VOICE = "voice"
    SUBTITLES = "subtitles"
    COMPOSED = "composed"
    THUMBNAIL = "thumbnail"
    AWAITING_GATE_B = "awaiting_gate_b"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class ColdOpenStyle(StrEnum):
    SCENE_FIRST = "scene_first"
    QUESTION_FIRST = "question_first"
    RECORD_QUOTE = "record_quote"
    TIMELINE_ANCHOR = "timeline_anchor"


class ThumbnailComposition(StrEnum):
    PORTRAIT_LEFT = "portrait_left"
    LOCATION_WIDE = "location_wide"
    ARTIFACT_CENTER = "artifact_center"
    SPLIT_THEN_NOW = "split_then_now"


class MotionType(StrEnum):
    STATIC = "static"
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PUSH_IN_SLOW = "push_in_slow"
    DRIFT = "drift"


class AssetKind(StrEnum):
    IMAGE = "image"
    AUDIO_MUSIC = "audio_music"
    AUDIO_SFX = "audio_sfx"
    FONT = "font"
    VIDEO = "video"


class LicenseType(StrEnum):
    CC0 = "cc0"
    PUBLIC_DOMAIN = "public_domain"
    YOUTUBE_AUDIO_LIBRARY = "youtube_audio_library"
    CC_BY = "cc_by"
    LICENSED = "licensed"
    GENERATED = "generated"


class Platform(StrEnum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


class PublicationStatus(StrEnum):
    PENDING = "pending"
    UPLOADING = "uploading"
    LIVE = "live"
    FAILED = "failed"
    REMOVED = "removed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


# --------------------------------------------------------------------------
# Stage transition validation
# --------------------------------------------------------------------------


class IllegalStageTransitionError(Exception):
    def __init__(self, current: PipelineStage, target: PipelineStage) -> None:
        self.current = current
        self.target = target
        super().__init__(f"cannot advance episode from {current} to {target}")


_STAGE_ORDER: tuple[PipelineStage, ...] = (
    PipelineStage.CREATED,
    PipelineStage.RESEARCHING,
    PipelineStage.FACTS_RECONCILED,
    PipelineStage.SCRIPTED,
    PipelineStage.AWAITING_GATE_A,
    PipelineStage.SHOT_LIST,
    PipelineStage.VISUALS,
    PipelineStage.VOICE,
    PipelineStage.SUBTITLES,
    PipelineStage.COMPOSED,
    PipelineStage.THUMBNAIL,
    PipelineStage.AWAITING_GATE_B,
    PipelineStage.PUBLISHING,
    PipelineStage.PUBLISHED,
)

_STAGE_INDEX: dict[PipelineStage, int] = {stage: i for i, stage in enumerate(_STAGE_ORDER)}


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


class Case(TimestampedModel, table=True):
    __tablename__ = "case"

    slug: str = Field(unique=True, index=True)
    title: str
    case_type: CaseType
    event_year: int
    country: str
    region: str | None = None
    summary: str
    resolution_status: ResolutionStatus
    living_persons_involved: bool
    risk_flags: list[RiskFlag] = Field(default_factory=list, sa_column=Column(SAJSON))
    documentation_score: int | None = None
    estimated_runtime_min: int | None = None
    monetization_tier: MonetizationTier = Field(default=MonetizationTier.UNKNOWN, index=True)
    legal_risk: LegalRisk = Field(default=LegalRisk.LOW)
    eligibility_notes: list[str] = Field(default_factory=list, sa_column=Column(SAJSON))
    status: CaseStatus = Field(default=CaseStatus.CANDIDATE, index=True)
    rejected_reason: str | None = None


class Source(TimestampedModel, table=True):
    __tablename__ = "source"

    case_id: int = Field(foreign_key="case.id", index=True)
    url: str
    domain: str
    publisher: str
    title: str
    published_date: date | None = None
    retrieved_at: datetime
    tier: SourceTier
    text_path: str
    text_sha256: str = Field(index=True)
    word_count: int


class Fact(TimestampedModel, table=True):
    __tablename__ = "fact"

    case_id: int = Field(foreign_key="case.id", index=True)
    statement: str
    fact_type: FactType
    occurred_at: str | None = None
    contested: bool = False
    contested_note: str | None = None
    confidence: float


class FactSource(TimestampedModel, table=True):
    __tablename__ = "fact_source"
    __table_args__ = (UniqueConstraint("fact_id", "source_id", name="uq_fact_source"),)

    fact_id: int = Field(foreign_key="fact.id", index=True)
    source_id: int = Field(foreign_key="source.id", index=True)


class VariationProfile(TimestampedModel, table=True):
    __tablename__ = "variation_profile"

    cold_open_style: ColdOpenStyle
    act_count: int
    narration_wpm: int
    shot_duration_mean_s: float
    shot_duration_sd_s: float
    transition_set: list[str] = Field(default_factory=list, sa_column=Column(SAJSON))
    music_present: bool
    music_intensity: float
    subtitle_style_id: int = Field(foreign_key="subtitle_style.id")
    thumbnail_composition: ThumbnailComposition


class Episode(TimestampedModel, table=True):
    __tablename__ = "episode"

    case_id: int = Field(foreign_key="case.id", index=True)
    variation_profile_id: int = Field(foreign_key="variation_profile.id")
    stage: PipelineStage = Field(default=PipelineStage.CREATED, index=True)
    gate_a_approved_at: datetime | None = None
    gate_b_approved_at: datetime | None = None
    structural_fingerprint: str = ""
    failed_at_stage: str | None = None
    error: str | None = None

    def advance_to(self, target: PipelineStage) -> None:
        """Move to `target`, raising IllegalStageTransitionError if not legal.

        The pipeline is a strict, linear sequence (see _STAGE_ORDER). FAILED is
        reachable from any non-terminal, non-failed stage; recovering from
        FAILED is only legal back into the exact stage that failed, so a
        failed render never forces re-researching. Gate A / Gate B approval
        timestamps must be set before crossing their respective gates.
        """
        current = self.stage

        if current == PipelineStage.PUBLISHED:
            raise IllegalStageTransitionError(current, target)

        if target == PipelineStage.FAILED:
            if current == PipelineStage.FAILED:
                raise IllegalStageTransitionError(current, target)
            self.failed_at_stage = current.value
            self.stage = PipelineStage.FAILED
            return

        if current == PipelineStage.FAILED:
            if target.value != self.failed_at_stage:
                raise IllegalStageTransitionError(current, target)
            self.stage = target
            self.failed_at_stage = None
            self.error = None
            return

        current_idx = _STAGE_INDEX.get(current)
        target_idx = _STAGE_INDEX.get(target)
        if current_idx is None or target_idx is None or target_idx != current_idx + 1:
            raise IllegalStageTransitionError(current, target)

        if target == PipelineStage.SHOT_LIST and self.gate_a_approved_at is None:
            raise IllegalStageTransitionError(current, target)
        if target == PipelineStage.PUBLISHING and self.gate_b_approved_at is None:
            raise IllegalStageTransitionError(current, target)

        self.stage = target


class Script(TimestampedModel, table=True):
    __tablename__ = "script"

    episode_id: int = Field(foreign_key="episode.id", index=True)
    version: int
    body: str
    word_count: int
    estimated_duration_s: int
    generated_by: str
    is_approved: bool = False


class ScriptEdit(TimestampedModel, table=True):
    __tablename__ = "script_edit"

    script_id: int = Field(foreign_key="script.id", index=True)
    version_before: int
    version_after: int
    diff: str
    edited_at: datetime = Field(default_factory=utcnow)


class ScriptCitation(TimestampedModel, table=True):
    __tablename__ = "script_citation"
    __table_args__ = (UniqueConstraint("script_id", "fact_id", name="uq_script_citation"),)

    script_id: int = Field(foreign_key="script.id", index=True)
    fact_id: int = Field(foreign_key="fact.id", index=True)


class Asset(TimestampedModel, table=True):
    __tablename__ = "asset"

    kind: AssetKind
    path: str
    sha256: str = Field(index=True)
    license: LicenseType
    license_url: str | None = None
    source_url: str | None = None
    attribution_required: bool = False
    attribution_text: str | None = None


class Shot(TimestampedModel, table=True):
    __tablename__ = "shot"

    episode_id: int = Field(foreign_key="episode.id", index=True)
    index: int
    script_span_start: int
    script_span_end: int
    direction: str
    duration_s: float
    motion: MotionType
    motion_params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SAJSON))
    asset_id: int | None = Field(default=None, foreign_key="asset.id")


class VoiceTrack(TimestampedModel, table=True):
    __tablename__ = "voice_track"

    episode_id: int = Field(foreign_key="episode.id", index=True)
    provider: str
    voice_id: str
    audio_path: str
    duration_s: float
    sample_rate: int


class Voice(TimestampedModel, table=True):
    __tablename__ = "voice"

    provider: str
    voice_id: str
    display_name: str
    gender: str
    accent: str
    age_range: str
    preview_path: str
    is_available: bool = True


class SubtitleStyle(TimestampedModel, table=True):
    __tablename__ = "subtitle_style"

    name: str
    font_family: str
    font_size: int
    primary_colour: str
    outline_colour: str
    outline_width: float
    shadow: float
    alignment: int
    margin_v: int
    max_chars_per_line: int


class SubtitleCue(TimestampedModel, table=True):
    __tablename__ = "subtitle_cue"

    episode_id: int = Field(foreign_key="episode.id", index=True)
    index: int
    start_ms: int
    end_ms: int
    text: str


class Render(TimestampedModel, table=True):
    __tablename__ = "render"

    episode_id: int = Field(foreign_key="episode.id", index=True)
    path: str
    width: int
    height: int
    fps: int
    duration_s: float
    file_size_bytes: int
    ffmpeg_command: str
    render_seconds: float


class Publication(TimestampedModel, table=True):
    __tablename__ = "publication"
    __table_args__ = (
        UniqueConstraint("platform", "platform_post_id", name="uq_publication_platform_post_id"),
    )

    episode_id: int = Field(foreign_key="episode.id", index=True)
    platform: Platform
    platform_post_id: str
    url: str
    title: str
    description: str
    tags: list[str] = Field(default_factory=list, sa_column=Column(SAJSON))
    published_at: datetime
    synthetic_content_disclosed: bool
    self_certification: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SAJSON))
    status: PublicationStatus = Field(default=PublicationStatus.PENDING)
    monetization_state: str | None = None


class MetricSnapshot(TimestampedModel, table=True):
    __tablename__ = "metric_snapshot"
    __table_args__ = (
        Index("ix_metric_snapshot_pub_time", "publication_id", "captured_at"),
    )

    publication_id: int = Field(foreign_key="publication.id", index=True)
    captured_at: datetime
    views: int
    impressions: int
    ctr: float
    avg_view_duration_s: float
    avg_percentage_viewed: float
    likes: int
    comments: int
    shares: int
    subscribers_gained: int
    estimated_revenue: float | None = None
    retention_curve: list[list[float]] = Field(default_factory=list, sa_column=Column(SAJSON))
    raw: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SAJSON))


class Job(TimestampedModel, table=True):
    __tablename__ = "job"
    __table_args__ = (Index("ix_job_status_schedule", "status", "scheduled_for"),)

    kind: str
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SAJSON))
    status: JobStatus = Field(default=JobStatus.QUEUED)
    attempts: int = 0
    max_attempts: int = 3
    last_error: str | None = None
    scheduled_for: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    episode_id: int | None = Field(default=None, foreign_key="episode.id")
