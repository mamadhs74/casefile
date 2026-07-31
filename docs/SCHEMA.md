# Data model

SQLModel + SQLite. All tables get `id` (int PK), `created_at`, `updated_at` unless noted.
Enums are Python `StrEnum` stored as text. JSON columns use SQLAlchemy `JSON`.

---

## Case

The library you browse and select from. One case can produce multiple episodes over time.

| field | type | notes |
|---|---|---|
| `slug` | str, unique | url-safe, e.g. `hinterkaifeck-1922` |
| `title` | str | working title, not the video title |
| `case_type` | CaseType | see enum |
| `event_year` | int | year the events occurred |
| `country` | str | ISO-3166 alpha-2 |
| `region` | str \| None | state/province |
| `summary` | str | 2–4 sentences, internal use |
| `resolution_status` | ResolutionStatus | see enum |
| `living_persons_involved` | bool | any non-public living individual named |
| `risk_flags` | JSON list[RiskFlag] | drives eligibility scoring |
| `documentation_score` | int 1–5 | how much primary record exists |
| `estimated_runtime_min` | int \| None | rough target length |
| `monetization_tier` | MonetizationTier | **computed**, never set by hand |
| `legal_risk` | LegalRisk | **computed** |
| `eligibility_notes` | JSON list[str] | **computed**, human-readable reasons |
| `status` | CaseStatus | workflow state |
| `rejected_reason` | str \| None | |

```python
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
    RECENT_EVENT = "recent_event"          # within 25 years
    POLITICAL_VIOLENCE = "political_violence"
    HATE_MOTIVATED = "hate_motivated"

class MonetizationTier(StrEnum):
    GREEN = "green"      # expect full ads
    YELLOW = "yellow"    # expect limited ads
    RED = "red"          # expect no ads — do not produce
    UNKNOWN = "unknown"

class LegalRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"        # do not produce

class CaseStatus(StrEnum):
    CANDIDATE = "candidate"
    RESEARCHING = "researching"
    READY = "ready"
    IN_PRODUCTION = "in_production"
    PUBLISHED = "published"
    REJECTED = "rejected"
```

### Eligibility scoring

Pure function in `packages/research/eligibility.py`. No DB access, fully unit-testable.
Recomputed on every write to `Case`. Returns `(tier, legal_risk, notes)`.

```
score_case(case) -> EligibilityResult
```

**RED — do not produce:**
- `CHILD_VICTIM` present. YouTube's shocking-content guidelines make content featuring
  young subjects in distress ineligible for ad revenue. No framing rescues this.
- `GRAPHIC_INJURY_CENTRAL` present. Advertiser guidelines: content where the focal point
  is blood, violence, or injury without other context is not suitable for advertising.
  If the injury *is* the story, there is no documentary framing that fixes it.
- `HATE_MOTIVATED` combined with `RECENT_EVENT`.

**HIGH legal risk — do not produce:**
- `ONGOING_LITIGATION`, or
- `NAMED_LIVING_SUSPECT` where `resolution_status` is not `CONVICTED`.
  Naming an unconvicted living person as a suspect is defamation exposure. This is
  independent of monetization and blocks production on its own.

**YELLOW:**
- `SEXUAL_VIOLENCE` or `SUICIDE_CENTRAL` present. The Jan 2026 guideline update allows
  full monetization for these when discussed non-graphically, but treat as yellow by
  default and let a script-level check promote to green after the style pass.
- `POLITICAL_VIOLENCE` present.
- `RECENT_EVENT` present.

**GREEN:**
- No blocking flags, `documentation_score >= 3`, `event_year` at least 25 years ago,
  `living_persons_involved` false.

**UNKNOWN:** `documentation_score` is null. Cannot score without knowing the record depth.

The API must refuse to create an `Episode` for a case that is RED or HIGH legal risk.
Raise `CaseNotEligibleError` with the notes attached.

---

## Source

Research provenance. Enforces R1.

| field | type | notes |
|---|---|---|
| `case_id` | FK Case | |
| `url` | str | |
| `domain` | str | derived, used for independence checks |
| `publisher` | str | |
| `title` | str | |
| `published_date` | date \| None | |
| `retrieved_at` | datetime | |
| `tier` | SourceTier | |
| `text_path` | str | path to extracted text on disk |
| `text_sha256` | str | integrity + dedupe |
| `word_count` | int | |

```python
class SourceTier(StrEnum):
    PRIMARY_RECORD = "primary_record"        # court filing, inquest, police report
    CONTEMPORANEOUS = "contemporaneous"      # news from the time of events
    RETROSPECTIVE = "retrospective"          # later journalism
    BOOK = "book"
    REFERENCE = "reference"                  # encyclopedic
    UNVERIFIED = "unverified"                # forums, wikis, content farms
```

`UNVERIFIED` sources may be stored as leads but never count toward the R1 gate and must
never be cited in a script.

### R1 gate

`packages/research/gate.py::check_source_gate(case_id) -> GateResult`

Passes only when all hold:
1. At least 3 sources with tier other than `UNVERIFIED`
2. At least 1 with tier `PRIMARY_RECORD`
3. At least 3 **distinct** `domain` values among them (independence)

Returns structured failure reasons, not a bare bool.

---

## Fact

The reconciled factual layer. Scripts are written from Facts, never from Source text.
This is the architectural reason the output is original expression rather than paraphrase.

| field | type | notes |
|---|---|---|
| `case_id` | FK Case | |
| `statement` | str | one atomic fact, plainly worded |
| `fact_type` | FactType | |
| `occurred_at` | str \| None | free-text date, may be approximate |
| `contested` | bool | sources disagree |
| `contested_note` | str \| None | how they disagree |
| `confidence` | float 0–1 | |

`FactType`: `EVENT`, `PERSON`, `LOCATION`, `TIMELINE`, `EVIDENCE`, `LEGAL_OUTCOME`,
`AFTERMATH`.

**`FactSource`** — join table (`fact_id`, `source_id`). A Fact with fewer than 2 sources
is flagged `contested=True` automatically unless its single source is `PRIMARY_RECORD`.

---

## Episode

One production run.

| field | type | notes |
|---|---|---|
| `case_id` | FK Case | |
| `variation_profile_id` | FK VariationProfile | |
| `stage` | PipelineStage | current position |
| `gate_a_approved_at` | datetime \| None | script approval |
| `gate_b_approved_at` | datetime \| None | cut approval |
| `structural_fingerprint` | str | hash of the variation dimensions |
| `failed_at_stage` | str \| None | |
| `error` | str \| None | |

```python
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
```

Stage transitions go through `Episode.advance_to(stage)`, which validates the transition
is legal. No direct assignment.

---

## VariationProfile

Enforces R2. Sampled per episode, never reused verbatim.

| field | type | notes |
|---|---|---|
| `cold_open_style` | ColdOpenStyle | 4 variants |
| `act_count` | int 3–5 | |
| `narration_wpm` | int 125–165 | |
| `shot_duration_mean_s` | float 3.5–9.0 | |
| `shot_duration_sd_s` | float | |
| `transition_set` | JSON list[str] | subset of available transitions |
| `music_present` | bool | |
| `music_intensity` | float 0–1 | |
| `subtitle_style_id` | FK SubtitleStyle | |
| `thumbnail_composition` | ThumbnailComposition | |

`ColdOpenStyle`: `SCENE_FIRST`, `QUESTION_FIRST`, `RECORD_QUOTE`, `TIMELINE_ANCHOR`.
`ThumbnailComposition`: `PORTRAIT_LEFT`, `LOCATION_WIDE`, `ARTIFACT_CENTER`, `SPLIT_THEN_NOW`.

### Similarity check

`packages/script/variation.py::check_similarity(profile, recent_profiles) -> float`

Encode the profile as a normalized feature vector, compute cosine similarity against the
last 10 published episodes' profiles. Returns the max. Above `0.85` the sampler resamples,
up to 20 attempts, then raises `VariationExhaustedError`. Do not silently proceed.

---

## Script, ScriptEdit

| Script field | type | notes |
|---|---|---|
| `episode_id` | FK Episode | |
| `version` | int | monotonic per episode |
| `body` | str | markdown, act-delimited |
| `word_count` | int | |
| `estimated_duration_s` | int | from word_count / wpm |
| `generated_by` | str | model identifier |
| `is_approved` | bool | |

`ScriptEdit` records every human change at Gate A: `script_id`, `version_before`,
`version_after`, `diff` (unified), `edited_at`. These are the audit trail proving
editorial control. Never delete them.

**`ScriptCitation`** — join (`script_id`, `fact_id`) recording which facts a script draws
on. A script citing fewer than 8 distinct facts is suspiciously thin; warn.

---

## Shot, Asset

| Shot field | type | notes |
|---|---|---|
| `episode_id` | FK Episode | |
| `index` | int | ordering |
| `script_span_start` | int | char offset into script body |
| `script_span_end` | int | |
| `direction` | str | what the shot depicts |
| `duration_s` | float | |
| `motion` | MotionType | |
| `motion_params` | JSON | zoom start/end, pan vector |
| `asset_id` | FK Asset \| None | |

`MotionType`: `STATIC`, `ZOOM_IN`, `ZOOM_OUT`, `PAN_LEFT`, `PAN_RIGHT`, `PUSH_IN_SLOW`,
`DRIFT`.

Motion params must keep the source image within bounds at every frame — validate before
render, not after. A zoom that exceeds the source resolution produces visible softening.

| Asset field | type | notes |
|---|---|---|
| `kind` | AssetKind | `IMAGE`, `AUDIO_MUSIC`, `AUDIO_SFX`, `FONT`, `VIDEO` |
| `path` | str | |
| `sha256` | str | |
| `license` | LicenseType | **required, no default** |
| `license_url` | str \| None | |
| `source_url` | str \| None | |
| `attribution_required` | bool | |
| `attribution_text` | str \| None | |

```python
class LicenseType(StrEnum):
    CC0 = "cc0"
    PUBLIC_DOMAIN = "public_domain"
    YOUTUBE_AUDIO_LIBRARY = "youtube_audio_library"
    CC_BY = "cc_by"
    LICENSED = "licensed"          # we hold a receipt
    GENERATED = "generated"        # produced by us
```

`AssetStore.add()` raises `UnlicensedAssetError` if `license` is missing. There is no
`UNKNOWN` license value on purpose — an asset whose license you cannot name is one you
cannot use.

---

## VoiceTrack, SubtitleStyle, SubtitleCue, Render

| VoiceTrack | type |
|---|---|
| `episode_id` | FK Episode |
| `provider` | str |
| `voice_id` | str |
| `audio_path` | str |
| `duration_s` | float |
| `sample_rate` | int |

**`Voice`** — the registry the UI reads for selection and preview: `provider`, `voice_id`,
`display_name`, `gender`, `accent`, `age_range`, `preview_path`, `is_available`.

**`SubtitleStyle`** — `name`, `font_family`, `font_size`, `primary_colour`,
`outline_colour`, `outline_width`, `shadow`, `alignment`, `margin_v`, `max_chars_per_line`.
Maps directly onto ASS style fields so rendering is a straight serialization.

**`SubtitleCue`** — `episode_id`, `index`, `start_ms`, `end_ms`, `text`. Timings come from
forced alignment against the rendered voice audio, not from estimation.

| Render | type | notes |
|---|---|---|
| `episode_id` | FK Episode | |
| `path` | str | |
| `width`, `height`, `fps` | int | |
| `duration_s` | float | |
| `file_size_bytes` | int | |
| `ffmpeg_command` | str | the exact command, for reproducibility |
| `render_seconds` | float | performance tracking |

---

## Publication, MetricSnapshot

| Publication | type | notes |
|---|---|---|
| `episode_id` | FK Episode | |
| `platform` | Platform | `YOUTUBE`, `TIKTOK`, `INSTAGRAM` |
| `platform_post_id` | str | the join key for analytics |
| `url` | str | |
| `title` | str | per-platform, they differ |
| `description` | str | |
| `tags` | JSON list[str] | |
| `published_at` | datetime | |
| `synthetic_content_disclosed` | bool | R5 |
| `self_certification` | JSON | the answers we submitted |
| `status` | PublicationStatus | `PENDING`, `UPLOADING`, `LIVE`, `FAILED`, `REMOVED` |
| `monetization_state` | str \| None | as reported by the platform |

**`MetricSnapshot`** — time series, never overwritten. `publication_id`, `captured_at`,
`views`, `impressions`, `ctr`, `avg_view_duration_s`, `avg_percentage_viewed`,
`likes`, `comments`, `shares`, `subscribers_gained`, `estimated_revenue`,
`retention_curve` (JSON, list of [percentage, audience_ratio]).

Snapshot cadence: hourly for 24h, then daily to 30d, then weekly. Store raw platform
response in a `raw` JSON column — platform APIs add fields and you'll want them later.

The whole point of keeping snapshots rather than totals: joining `MetricSnapshot` against
`VariationProfile` is what eventually tells you which structural choices hold retention.
Design the query path for that from the start.

---

## Job

| field | type |
|---|---|
| `kind` | str |
| `payload` | JSON |
| `status` | `QUEUED`, `RUNNING`, `DONE`, `FAILED`, `CANCELLED` |
| `attempts` | int |
| `max_attempts` | int |
| `last_error` | str \| None |
| `scheduled_for` | datetime |
| `started_at`, `finished_at` | datetime \| None |
| `episode_id` | FK Episode \| None |

Worker claims jobs with `UPDATE ... WHERE status='QUEUED' AND id=(SELECT ...) RETURNING`
so a second worker can't double-claim. Exponential backoff on retry.

---

## Indexes

- `case.slug` unique, `case.status`, `case.monetization_tier`
- `source.case_id`, `source.text_sha256`
- `fact.case_id`
- `episode.case_id`, `episode.stage`
- `publication.platform_post_id` unique per platform
- `metric_snapshot.(publication_id, captured_at)` composite
- `job.(status, scheduled_for)` composite
