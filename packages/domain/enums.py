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


# docs/SOURCING.md's Tier A boundary, mapped onto the finer-grained SourceTier
# values above: citable-and-narratable sources are exactly these two. Tier B
# (RETROSPECTIVE, BOOK, REFERENCE, UNVERIFIED) may be stored as leads but never
# cited on a narratable Claim -- see packages/db/listeners.py. Tier C isn't
# represented here at all: those sources are excluded at the fetch layer and
# never become Source rows in the first place.
TIER_A_SOURCE_TIERS: frozenset[SourceTier] = frozenset(
    {SourceTier.PRIMARY_RECORD, SourceTier.CONTEMPORANEOUS}
)


class ArchiveProvider(StrEnum):
    """docs/ARCHIVE-SPEC.md. A Strategy names which of these its sourcing may use."""

    WIKIMEDIA_COMMONS = "wikimedia_commons"
    INTERNET_ARCHIVE = "internet_archive"
    LIBRARY_OF_CONGRESS = "library_of_congress"
    EUROPEANA = "europeana"
    PEXELS = "pexels"
    PIXABAY = "pixabay"


class ClaimCategory(StrEnum):
    """Subject-matter axis -- what the claim is *about*. Renamed from the old,
    unused FactType; same seven values, so "show me all evidence claims"
    keeps working. Orthogonal to ClaimType below, which is about how the
    claim is *known*, not what it's about -- the two are deliberately not
    collapsed into one field."""

    EVENT = "event"
    PERSON = "person"
    LOCATION = "location"
    TIMELINE = "timeline"
    EVIDENCE = "evidence"
    LEGAL_OUTCOME = "legal_outcome"
    AFTERMATH = "aftermath"


class ClaimType(StrEnum):
    """Epistemic axis -- docs/SOURCING.md's claim table `type` field. Distinct
    from a fact about the case (FACT) is a fact about what was reported
    (CONTEMPORANEOUS_REPORT); the script generator is required to preserve
    this distinction in its phrasing, not flatten it."""

    FACT = "fact"
    CONTEMPORANEOUS_REPORT = "contemporaneous_report"
    DISPUTED = "disputed"
    INFERENCE = "inference"


class ClaimConfidence(StrEnum):
    ESTABLISHED = "established"
    REPORTED = "reported"
    CONTESTED = "contested"


class EntityRole(StrEnum):
    VICTIM = "victim"
    SUSPECT = "suspect"
    WITNESS = "witness"
    INVESTIGATOR = "investigator"
    COMMENTATOR = "commentator"


class ImageRights(StrEnum):
    PUBLIC_DOMAIN = "public_domain"
    LICENSED = "licensed"
    NONE = "none"


class EpisodeArchitecture(StrEnum):
    """docs/SOURCING.md's variation manifest. Selects narrative structure in
    stage 1; not to be confused with VariationProfile's render-level
    dimensions (cold open style, pacing, transitions), which it will
    eventually influence once packages/script exists to wire the two
    together -- see docs/SCHEMA.md."""

    CHRONOLOGICAL = "chronological"
    INVESTIGATION_LED = "investigation_led"
    RECORD_FORWARD = "record_forward"
    MISCONCEPTION = "misconception"
    OPEN_QUESTION = "open_question"
    CONTEXT_FIRST = "context_first"


class UniquenessCheckStatus(StrEnum):
    """Result of checking an Episode's generation_fingerprint against the
    (not-yet-built) hosted uniqueness registry -- see docs/SCHEMA.md.
    LOCAL_ONLY means the registry was unreachable: generation proceeded
    anyway (a network failure must never block a user's work), verified
    only against this installation's own Episodes via the DB-level
    UNIQUE(subject_id, generation_fingerprint) constraint."""

    NOT_CHECKED = "not_checked"
    LOCAL_ONLY = "local_only"
    VERIFIED_UNIQUE = "verified_unique"
    COLLISION_DETECTED = "collision_detected"


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
    FACEBOOK = "facebook"


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
