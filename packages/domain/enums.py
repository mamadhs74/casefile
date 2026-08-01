"""Shared vocabulary for casefile.

These StrEnums are the contract between the persistence layer (packages/db),
business logic (packages/research, packages/script, ...), and the API. This
module must never import from packages/db or packages/research — everything
else imports from here, not the other way around.

CaseType and RiskFlag are NOT here. They moved to
packages/strategies/criminal_cases/enums.py: they're that strategy's own
category and risk vocabulary, not a universal one every strategy must share.
See docs/SCHEMA.md's "Strategy" section for why. MonetizationTier and
LegalRisk stay here on purpose — every strategy scores into the same output
vocabulary, or the one-glance cross-strategy triage view stops meaning
anything.
"""

from __future__ import annotations

from enum import StrEnum


class ResolutionStatus(StrEnum):
    CONVICTED = "convicted"
    ACQUITTED = "acquitted"
    UNSOLVED = "unsolved"
    OFFICIALLY_RULED = "officially_ruled"
    DISPUTED = "disputed"


class MonetizationTier(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    UNKNOWN = "unknown"


class LegalRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SubjectStatus(StrEnum):
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


class ArchiveProvider(StrEnum):
    """docs/ARCHIVE-SPEC.md. A Strategy names which of these its sourcing may use."""

    WIKIMEDIA_COMMONS = "wikimedia_commons"
    INTERNET_ARCHIVE = "internet_archive"
    LIBRARY_OF_CONGRESS = "library_of_congress"
    EUROPEANA = "europeana"
    PEXELS = "pexels"
    PIXABAY = "pixabay"


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
    CC_BY_SA = "cc_by_sa"
    PLATFORM_FREE = "platform_free"  # bespoke free-to-use catalog license, e.g. Pexels/Pixabay
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
