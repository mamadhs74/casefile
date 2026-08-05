"""SQLModel table definitions for casefile.

Mirrors docs/SCHEMA.md exactly. Every table gets id/created_at/updated_at via
`TimestampedModel` unless the schema doc notes otherwise (it doesn't, here).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON as SAJSON
from sqlalchemy import Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from packages.domain.enums import (
    ArchiveProvider,
    AssetKind,
    ClaimCategory,
    ClaimConfidence,
    ClaimType,
    ColdOpenStyle,
    EntityRole,
    EpisodeArchitecture,
    ImageRights,
    JobStatus,
    LegalRisk,
    LicenseType,
    MonetizationTier,
    MotionType,
    PipelineStage,
    Platform,
    PublicationStatus,
    ResolutionStatus,
    SourceTier,
    SubjectStatus,
    ThumbnailComposition,
    UniquenessCheckStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampedModel(SQLModel):
    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


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


class Strategy(TimestampedModel, table=True):
    """One content vertical: its own eligibility rules, sourcing policy, and
    (eventually) channels. slug doubles as the lookup key into
    packages/strategies/<slug>/ -- see packages/research/dispatch.py.

    min_verified_sources / min_primary_records / min_distinct_domains are
    R1's gate thresholds, tunable per strategy (unlike the eligibility logic
    itself, these are just numbers -- see docs/SCHEMA.md for why the two are
    treated differently). There is deliberately no general-purpose update
    endpoint for these fields: they come from a migration/seed, not a live
    admin surface, so weakening R1 requires a code change someone reviews.
    """

    __tablename__ = "strategy"

    slug: str = Field(unique=True, index=True)
    name: str
    description: str
    subject_noun_singular: str
    subject_noun_plural: str
    min_verified_sources: int
    min_primary_records: int
    min_distinct_domains: int
    style_guide: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SAJSON))
    allowed_archive_providers: list[ArchiveProvider] = Field(
        default_factory=list, sa_column=Column(SAJSON)
    )
    is_active: bool = Field(default=True)


class Subject(TimestampedModel, table=True):
    """The library you browse and select from. One subject can produce multiple
    episodes over time. Generalized from what used to be Case -- see docs/SCHEMA.md.

    risk_flags and attributes are both strategy-owned vocabulary stored as
    plain JSON/text; packages/db/listeners.py validates both against the
    subject's own strategy on every write, the same way monetization_tier
    has always been computed rather than trusted from the caller.
    """

    __tablename__ = "subject"

    strategy_id: int = Field(foreign_key="strategy.id", index=True)
    slug: str = Field(unique=True, index=True)
    title: str
    event_year: int
    country: str
    region: str | None = None
    summary: str
    resolution_status: ResolutionStatus
    living_persons_involved: bool
    risk_flags: list[str] = Field(default_factory=list, sa_column=Column(SAJSON))
    attributes: dict[str, Any] = Field(default_factory=dict, sa_column=Column(SAJSON))
    documentation_score: int | None = None
    estimated_runtime_min: int | None = None
    monetization_tier: MonetizationTier = Field(default=MonetizationTier.UNKNOWN, index=True)
    legal_risk: LegalRisk = Field(default=LegalRisk.LOW)
    eligibility_notes: list[str] = Field(default_factory=list, sa_column=Column(SAJSON))
    status: SubjectStatus = Field(default=SubjectStatus.CANDIDATE, index=True)
    rejected_reason: str | None = None


class Source(TimestampedModel, table=True):
    """A Tier B "syndicated copy at a second URL" and the original are the
    same content by definition -- (subject_id, text_sha256) is unique so
    that can't silently inflate R1's source-diversity gate, which has real
    monetization meaning. Two byte-identical Source rows for one subject
    is not duplicate-waste, it's a gate passing when it shouldn't.
    packages/research/fetch.py checks this before ever attempting the
    insert; this constraint is the backstop for every other write path.
    """

    __tablename__ = "source"
    __table_args__ = (
        UniqueConstraint("subject_id", "text_sha256", name="uq_source_subject_text_sha256"),
    )

    subject_id: int = Field(foreign_key="subject.id", index=True)
    url: str
    domain: str = Field(default="")  # derived from url, see packages/db/listeners.py
    publisher: str
    title: str
    published_date: date | None = None
    retrieved_at: datetime
    tier: SourceTier
    text_path: str
    text_sha256: str = Field(index=True)
    word_count: int


class Claim(TimestampedModel, table=True):
    """The reconciled factual layer -- docs/SOURCING.md's claim table.
    Scripts are written from Claims, never from Source text: the
    architectural reason the output is original expression rather than
    paraphrase. Renamed and extended from the old, never-wired-up Fact.

    category and claim_type are deliberately separate axes: category is
    what the claim is about (event, evidence, location, ...), claim_type is
    how it's known (a fact about the case vs. a fact about what was
    reported). Collapsing them would lose the ability to ask "show me all
    evidence claims" independent of their epistemic status.

    narratable defaults False and cannot be set True at creation -- see
    packages/db/listeners.py. It can only become True once the claim has at
    least one source and every one of them is Tier A
    (packages.domain.enums.TIER_A_SOURCE_TIERS); this is enforced at the
    persistence layer, not just checked at write time by convention.
    """

    __tablename__ = "claim"

    subject_id: int = Field(foreign_key="subject.id", index=True)
    statement: str
    category: ClaimCategory
    claim_type: ClaimType
    confidence: ClaimConfidence
    contested_note: str | None = None
    # Free text, not `date`: real historical claims are often only precise
    # to a month or a season. Forcing a `date` column would mean inventing
    # a fake day for those. If strict chronological sorting is ever needed,
    # add a separate nullable sort_date alongside this rather than
    # tightening it -- see docs/SCHEMA.md.
    date_anchor: str | None = None
    narratable: bool = Field(default=False)


class ClaimSource(TimestampedModel, table=True):
    """quoted_span/span_start/span_end are the verifiability mechanism --
    see docs/SCHEMA.md's claim-extraction section. quoted_span is a
    verbatim (exact-substring) copy of the passage in this source's text
    that supports the claim; span_start/span_end are its character
    offsets in that text, computed by locating quoted_span, not emitted
    by a model. All three are required: this system's whole point is
    that a reviewer can see claim and supporting passage side by side in
    seconds, and that only holds if every ClaimSource carries one. This
    makes citations structurally verifiable -- the quote provably exists
    where claimed -- but not semantically verifiable -- that the claim
    actually follows from it. That second check is a human's job.
    """

    __tablename__ = "claim_source"
    __table_args__ = (UniqueConstraint("claim_id", "source_id", name="uq_claim_source"),)

    claim_id: int = Field(foreign_key="claim.id", index=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    quoted_span: str
    span_start: int
    span_end: int


class Entity(TimestampedModel, table=True):
    """A named person in a Subject's record -- docs/SOURCING.md's entity
    table. Subject-scoped, not global: the same real person appearing
    across multiple subjects is out of scope for this pass (no cross-
    subject dedup exists), simpler for now and not a breaking choice to
    revisit later.

    living is indexed on purpose, not just typed: it gates render (a living,
    named individual trips R8 and blocks render pending review) and is
    expected to be filtered on, not just stored.

    adjudicated is descriptive only for this pass -- it isn't wired into
    LegalRisk scoring or anything else yet.
    """

    __tablename__ = "entity"

    subject_id: int = Field(foreign_key="subject.id", index=True)
    name: str
    role: EntityRole
    living: bool = Field(index=True)
    adjudicated: bool
    image_rights: ImageRights


class ClaimEntity(TimestampedModel, table=True):
    __tablename__ = "claim_entity"
    __table_args__ = (UniqueConstraint("claim_id", "entity_id", name="uq_claim_entity"),)

    claim_id: int = Field(foreign_key="claim.id", index=True)
    entity_id: int = Field(foreign_key="entity.id", index=True)


class VariationProfile(TimestampedModel, table=True):
    """Enforces R2. strategy_id scopes the similarity-check comparison pool

    -- "last 10 published" means last 10 for this strategy, not across every
    strategy's channels. Nothing reads this field yet (packages/script isn't
    built); it's added now so the column exists before the similarity-check
    implementation has to choose between a migration and silently comparing
    across strategies.
    """

    __tablename__ = "variation_profile"

    strategy_id: int = Field(foreign_key="strategy.id", index=True)
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
    """A specific thesis + architecture + ordered claim selection over a
    Subject -- not a Subject property. Many Episodes may exist per Subject:
    two users (or the same user twice) covering the same case are expected
    to produce different Episodes, which is the entire reason thesis,
    architecture, and claim selection live here and not on Subject.

    generation_fingerprint hashes (thesis, architecture, ordered claim ID
    list) -- deliberately the *input* to generation, never the generated
    script text. Checking output-text similarity (or worse, varying LLM
    temperature/seed to dodge such a check) is exactly the weak
    differentiation docs/POLICY.md's Bucket 1 names: different wording over
    an identical skeleton is still the same skeleton. It is `str | None`,
    not `""`, on purpose -- see the UniqueConstraint below.

    uniqueness_check records the result of checking generation_fingerprint
    against a hosted uniqueness registry that is NOT built yet -- see
    docs/SCHEMA.md. That registry does not exist, so nothing sets this to
    VERIFIED_UNIQUE or COLLISION_DETECTED today; it only exists so the
    column is there when the registry is. A network failure must never
    block a user's work: LOCAL_ONLY means exactly that happened, generation
    proceeded anyway, and only the local UNIQUE constraint below actually
    guarded it.
    """

    __tablename__ = "episode"
    __table_args__ = (
        UniqueConstraint(
            "subject_id", "generation_fingerprint", name="uq_episode_subject_fingerprint"
        ),
    )

    subject_id: int = Field(foreign_key="subject.id", index=True)
    variation_profile_id: int = Field(foreign_key="variation_profile.id")
    stage: PipelineStage = Field(default=PipelineStage.CREATED, index=True)
    gate_a_approved_at: datetime | None = None
    gate_b_approved_at: datetime | None = None
    structural_fingerprint: str = ""
    failed_at_stage: str | None = None
    error: str | None = None
    thesis: str | None = None
    architecture: EpisodeArchitecture | None = None
    generation_fingerprint: str | None = Field(default=None, index=True)
    uniqueness_check: UniquenessCheckStatus = Field(default=UniquenessCheckStatus.NOT_CHECKED)

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


class EpisodeClaim(TimestampedModel, table=True):
    """An Episode's ordered claim selection. position preserves narrative
    order, which architecture (not this table) determines the meaning of.

    A row referencing a Claim whose narratable is not True is rejected at
    insert -- see packages/db/listeners.py. narratable is meaningless if it
    can be bypassed one hop downstream at episode assembly.
    """

    __tablename__ = "episode_claim"
    __table_args__ = (UniqueConstraint("episode_id", "claim_id", name="uq_episode_claim"),)

    episode_id: int = Field(foreign_key="episode.id", index=True)
    claim_id: int = Field(foreign_key="claim.id", index=True)
    position: int


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
    __table_args__ = (UniqueConstraint("script_id", "claim_id", name="uq_script_citation"),)

    script_id: int = Field(foreign_key="script.id", index=True)
    claim_id: int = Field(foreign_key="claim.id", index=True)


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


class Channel(TimestampedModel, table=True):
    """A credentialed publish target: one strategy's account on one platform.

    strategy_id + platform is NOT unique -- a strategy may run more than one
    channel on the same platform (that's the whole reason Publication gets
    channel_id below instead of continuing to rely on platform alone).
    (platform, external_account_id) is unique instead: the same real-world
    account should never be registered as two different Channel rows.

    credentials_ref names a macOS Keychain entry -- a reference, never the
    secret itself. See docs/SCHEMA.md and CLAUDE.md's secret-handling rule:
    no token, key, or credential value is ever stored in this table or
    anywhere in the database. The keyring integration that resolves this
    reference at publish time isn't built yet; this column exists so the
    reference has somewhere to live once it is.
    """

    __tablename__ = "channel"
    __table_args__ = (
        UniqueConstraint(
            "platform", "external_account_id", name="uq_channel_platform_external_account"
        ),
    )

    strategy_id: int = Field(foreign_key="strategy.id", index=True)
    platform: Platform
    display_name: str
    external_account_id: str
    credentials_ref: str
    is_active: bool = Field(default=True)


class Publication(TimestampedModel, table=True):
    __tablename__ = "publication"
    __table_args__ = (
        UniqueConstraint("platform", "platform_post_id", name="uq_publication_platform_post_id"),
    )

    episode_id: int = Field(foreign_key="episode.id", index=True)
    channel_id: int = Field(foreign_key="channel.id", index=True)
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
