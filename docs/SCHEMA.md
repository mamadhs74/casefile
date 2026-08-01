# Data model

SQLModel + SQLite. All tables get `id` (int PK), `created_at`, `updated_at` unless noted.
Enums are Python `StrEnum` stored as text. JSON columns use SQLAlchemy `JSON`.

casefile is multi-strategy: criminal cases are one **Strategy** among several a future
strategy could add. Read this document's first three sections together before touching
`packages/db/models.py` — they explain a deliberate split between what's shared across
every strategy and what each strategy owns for itself, and getting that split wrong
either re-couples strategies that should be independent or loses guarantees (R1, R7)
that used to be automatic. See `packages/strategies/criminal_cases/` for the first (and
so far only) strategy, migrated from what used to be a single, hardcoded content model.

---

## Strategy

One row per content vertical. Holds identity, sourcing policy, and script-style
guidance as **data** — and, separately, a `slug` that is also the lookup key into that
strategy's own Python package (`packages/strategies/<slug>/`), which holds its risk-flag
vocabulary, its category vocabulary, and its eligibility scoring logic as **code**.

| field | type | notes |
|---|---|---|
| `slug` | str, unique | e.g. `criminal-cases`. Also the dispatch registry key — see below |
| `name` | str | display name |
| `description` | str | |
| `subject_noun_singular` | str | e.g. "case" — operator-facing copy, not the schema's own "subject" |
| `subject_noun_plural` | str | e.g. "cases" |
| `min_verified_sources` | int | R1 gate threshold |
| `min_primary_records` | int | R1 gate threshold |
| `min_distinct_domains` | int | R1 gate threshold |
| `style_guide` | JSON | tone target, forbidden-phrase list — prose guidance, not branching logic |
| `allowed_archive_providers` | JSON list[ArchiveProvider] | which of docs/ARCHIVE-SPEC.md's providers this strategy's sourcing may use |
| `is_active` | bool | a strategy can be retired without deleting its history |

```python
class ArchiveProvider(StrEnum):
    WIKIMEDIA_COMMONS = "wikimedia_commons"
    INTERNET_ARCHIVE = "internet_archive"
    LIBRARY_OF_CONGRESS = "library_of_congress"
    EUROPEANA = "europeana"
    PEXELS = "pexels"
    PIXABAY = "pixabay"
```

### Why data here and code there

The gate's three thresholds are *numbers* — safe to vary per strategy without a code
review, because the shape of the check itself (three named failure reasons, still
enforced by one shared function) never changes. `NAMED_LIVING_SUSPECT` combined with
`resolution_status != CONVICTED` implying `HIGH` legal risk is a defamation-law judgment
call with a hardcoded rationale — that's code, and turning it into a generic rule-engine
config would blur exactly the kind of crisp, auditable logic eligibility scoring needs to
stay. The dividing line: if getting it wrong changes a legal or monetization outcome via
a non-obvious combination of conditions, it's code under `packages/strategies/<slug>/`;
if it's a tunable number or prose guidance, it's a column on `Strategy`.

**A consequence worth being deliberate about:** because gate thresholds are database rows
rather than module constants, they're editable at runtime in a way the old
`MIN_VERIFIED_SOURCES = 3` constant never was. There is intentionally no general-purpose
`PATCH /strategies/{id}` endpoint — a strategy's thresholds come from a migration or seed
script that someone reviews, not a live admin surface. Weakening R1 for a strategy should
require a code change, even though the value itself lives in a column.

`strategy_id` on `Subject` is set once at creation and never changes — `risk_flags` and
`attributes` are shaped by whichever strategy a subject belongs to, so reassigning a
subject to a different strategy would orphan or invalidate both. There is no
`strategy_id` field on `SubjectUpdate`.

**Registering a strategy is two steps, not one:** a `Strategy` row (the data — name,
thresholds, style guide) and a Python package under `packages/strategies/<slug>/` that
registers itself with `packages/research/dispatch.py` on import (the code — risk-flag
enum, attribute shape, eligibility scorer). A strategy only fully exists once both are
present; a `Strategy` row with no matching code registration fails loudly
(`UnknownStrategyError`) the moment anything tries to validate or score a subject
against it, rather than silently doing nothing.

---

## Subject

The library you browse and select from. One subject can produce multiple episodes over
time. Generalized from what used to be `Case` — see the framing note at the top of this
document. `slug`, `title`, `summary`, `event_year`, `country`, `region`,
`resolution_status`, `living_persons_involved`, and `documentation_score` stayed
first-class shared columns on purpose: they're true of any documentary subject
regardless of strategy, and the operator needs to filter/sort across strategies by them
in one triage view — burying them in a per-strategy blob would break that view.

| field | type | notes |
|---|---|---|
| `strategy_id` | FK Strategy | immutable after creation |
| `slug` | str, unique | url-safe |
| `title` | str | working title, not the video title |
| `event_year` | int | year the events occurred |
| `country` | str | ISO-3166 alpha-2 |
| `region` | str \| None | state/province |
| `summary` | str | 2–4 sentences, internal use |
| `resolution_status` | ResolutionStatus | see enum — stays shared, see below |
| `living_persons_involved` | bool | any non-public living individual named — stays shared, R7 |
| `risk_flags` | JSON list[str] | strategy-owned vocabulary, see below |
| `attributes` | JSON dict | strategy-owned extra fields, see below |
| `documentation_score` | int 1–5 \| None | how much primary record exists |
| `estimated_runtime_min` | int \| None | rough target length |
| `monetization_tier` | MonetizationTier | **computed**, never set by hand, never strategy-specific |
| `legal_risk` | LegalRisk | **computed**, never set by hand, never strategy-specific |
| `eligibility_notes` | JSON list[str] | **computed**, human-readable reasons |
| `status` | SubjectStatus | workflow state, renamed from CaseStatus, values unchanged |
| `rejected_reason` | str \| None | |

```python
class ResolutionStatus(StrEnum):
    CONVICTED = "convicted"
    ACQUITTED = "acquitted"
    UNSOLVED = "unsolved"
    OFFICIALLY_RULED = "officially_ruled"
    DISPUTED = "disputed"

class SubjectStatus(StrEnum):
    CANDIDATE = "candidate"
    RESEARCHING = "researching"
    READY = "ready"
    IN_PRODUCTION = "in_production"
    PUBLISHED = "published"
    REJECTED = "rejected"
```

### The one thing that must not vary by strategy

`MonetizationTier` and `LegalRisk` are global, not per-strategy, and this is
non-negotiable: every strategy scores into the *same* output vocabulary, or the
one-glance, colour-coded triage view across every subject in the library — the entire
point of the product — stops meaning anything. A strategy's *inputs* to eligibility
scoring can and do specialize (see risk_flags below); its *outputs* cannot.

```python
class MonetizationTier(StrEnum):
    GREEN = "green"      # expect full ads
    YELLOW = "yellow"    # expect limited ads
    RED = "red"          # expect no ads — do not produce
    UNKNOWN = "unknown"

class LegalRisk(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"        # do not produce
```

### `risk_flags` — strategy-owned, validated at dispatch time

`RiskFlag` used to be one closed, crime-specific `StrEnum` in `packages/domain/enums.py`.
Forcing every future strategy to reuse it would make strategy-specific risk factors
unrepresentable, or balloon it into a kitchen-sink enum irrelevant to most strategies.
So `Subject.risk_flags` is `list[str]` at the storage layer, and each strategy defines
its *own* `RiskFlag` enum under its own package
(`packages/strategies/criminal_cases/enums.py` for the first one).

The loosening from a closed enum to `list[str]` is real, not a shortcut — a wrong or
misspelled flag is no longer impossible to construct at the type level the way it used
to be. The mitigation is that **the registry parses, not the scorer**:
`packages/research/dispatch.py::score_subject` resolves the subject's strategy, parses
every string in `risk_flags` into that strategy's own enum, and raises
`UnknownRiskFlagError` immediately on anything that doesn't match — before a scorer ever
runs. A scorer's function signature only accepts `frozenset[<its own enum>]`; there is no
code path by which caller discipline could hand it an unvalidated string. See "Eligibility
scoring" below.

### `attributes` — strategy-owned extra fields

Whatever a strategy needs that isn't one of the shared columns above. For
`criminal-cases`, that's just `case_type`:

```python
# packages/strategies/criminal_cases/enums.py
class CaseType(StrEnum):
    HOMICIDE = "homicide"
    DISAPPEARANCE = "disappearance"
    UNEXPLAINED_EVENT = "unexplained_event"
    HISTORICAL_HORROR = "historical_horror"
    MARITIME = "maritime"
    DISASTER = "disaster"
    INSTITUTIONAL_ABUSE = "institutional_abuse"
```

All seven values stayed with `criminal-cases` on migration — undivided, even though
`historical_horror`/`maritime`/`disaster` don't read as crime types. Splitting that
taxonomy apart is a real product decision, not a mechanical one, and it's deferred until
a second strategy actually claims one of these values.

Each strategy registers a Pydantic model (`extra="forbid"`, same reasoning as
`SubjectCreate`) describing its attributes shape —
`packages/strategies/criminal_cases/attributes.py::Attributes` for this one.
`packages/db/listeners.py` validates and normalizes `Subject.attributes` against it on
every write, the same way `monetization_tier` has always been computed rather than
trusted from the caller: even a hand-set, invalid `attributes` dict through a raw session
bypassing the API gets rejected, not silently stored.

### Enforcement: unconditional, at the persistence layer

`packages/db/listeners.py`'s `before_insert`/`before_update` listener on `Subject`:

1. Resolves `target.strategy_id` to that strategy's `slug` (a query against the
   `Strategy` table via the raw connection the listener receives — this is the one place
   the mechanism needs a DB read, since the code registry is keyed by slug and a `Subject`
   row only stores the FK integer).
2. Validates and normalizes `target.attributes` against that strategy's registered model.
3. Runs that strategy's eligibility scorer and sets `monetization_tier`, `legal_risk`,
   `eligibility_notes` — unconditionally, overwriting anything the caller set.

No code path — API, script, direct session use — can produce a `Subject` row with
computed fields that don't match what its own strategy would compute, or with
`attributes`/`risk_flags` that don't validate against its own strategy's shape.

---

## Eligibility scoring and strategy dispatch

`packages/research/dispatch.py`. Each strategy owns its scoring logic as code
(`packages/strategies/<slug>/eligibility.py`); this module is the single place that
resolves a strategy slug to that code and hands it already-validated, already-typed
data.

```python
@dataclass(frozen=True)
class TypedEligibilityInput[E: StrEnum]:
    risk_flags: frozenset[E]
    resolution_status: ResolutionStatus
    event_year: int
    documentation_score: int | None
    living_persons_involved: bool

class Scorer[E: StrEnum](Protocol):
    def __call__(self, subject: TypedEligibilityInput[E]) -> EligibilityResult: ...

@dataclass(frozen=True)
class StrategyDefinition[E: StrEnum]:
    slug: str
    risk_flag_enum: type[E]
    scorer: Scorer[E]
    attributes_model: type[BaseModel]
```

`register_strategy(definition)` — called as an import side effect by each strategy
package, mirroring how `packages/db/listeners.py` itself gets registered (see
`packages/db/session.py`). `packages/db/listeners.py` imports every known strategy
package for exactly this reason; a strategy that's never imported is never findable.

`score_subject(raw: EligibilityInput, strategy_slug: str) -> EligibilityResult` — the
one entry point. Pure, touches no DB (same guarantee the old `score_case()` made), which
is why `POST /subjects/preview-eligibility` can still score a not-yet-persisted subject
without a database round trip: the API payload carries `strategy_slug` (a string, known
at code-registration time), not `strategy_id` (a database-assigned integer that would
require a lookup). `strategy_id` only gets resolved, once, on the path that actually
persists a `Subject`.

`EligibilityInput` (`packages/domain/protocols.py`) is the structural contract both
`Subject` and `SubjectCreate` satisfy — reused almost unchanged from the single-strategy
version. Four of its five fields are untouched (`resolution_status`, `event_year`,
`documentation_score`, `living_persons_involved` — all judged to be genuinely universal).
Only `risk_flags` changed, from `list[RiskFlag]` to `list[str]`, and only because of the
per-strategy vocabulary reasoning above.

```python
class EligibilityInput(Protocol):
    risk_flags: list[str]
    resolution_status: ResolutionStatus
    event_year: int
    documentation_score: int | None
    living_persons_involved: bool
```

`packages/research/eligibility.py` keeps only what's genuinely strategy-agnostic:
`EligibilityResult` (the shared output shape) and `ensure_eligible_for_episode()`, which
blocks Episode creation on `RED` tier or `HIGH` legal risk. Neither needed to change —
they only ever look at the universal tier/legal_risk output, never at how a strategy
arrived at it. `CaseNotEligibleError` is renamed `SubjectNotEligibleError`.

### `criminal-cases`, the first strategy

`packages/strategies/criminal_cases/` — `enums.py` (`CaseType`, `RiskFlag`, both moved
here unchanged from `packages/domain/enums.py`), `attributes.py` (the `case_type`
attribute model), `eligibility.py` (the actual scoring rules, ported unchanged in
substance from the old global `score_case()`), and `__init__.py` (registers all of the
above with the dispatch registry on import).

**RED — do not produce:**
- `CHILD_VICTIM` present.
- `GRAPHIC_INJURY_CENTRAL` present.
- `HATE_MOTIVATED` combined with `RECENT_EVENT`.

**HIGH legal risk — do not produce:**
- `ONGOING_LITIGATION`, or
- `NAMED_LIVING_SUSPECT` where `resolution_status` is not `CONVICTED`.

**YELLOW:** `SEXUAL_VIOLENCE` or `SUICIDE_CENTRAL`, `POLITICAL_VIOLENCE`, or
`RECENT_EVENT` present.

**GREEN:** no blocking flags, `documentation_score >= 3`, `event_year` at least 25 years
ago, `living_persons_involved` false.

**UNKNOWN:** `documentation_score` is null.

None of this changed on migration — moving to a strategy package is not a policy change.

### Cross-strategy conformance

`tests/test_strategy_conformance.py` — invariants checked against *every registered*
strategy, not against `criminal-cases` specifically. This exists because R7 used to be
enforced for free: `criminal-cases`' scorer was the only scorer that existed, so every
subject ran through it and there was no way to add a subject that skipped the check.
Once a second strategy registers its own scorer, that stops being true by construction —
a new strategy's author has to remember to encode an equivalent protection themselves.
The suite iterates `packages/research/dispatch.py::iter_strategy_definitions()` so a
strategy that forgets fails CI instead of failing silently in production. It starts with
one invariant (`living_persons_involved=True` can never score `LOW` legal risk) and is
meant to grow as more cross-strategy invariants get identified.

---

## Source

Research provenance. Enforces R1.

| field | type | notes |
|---|---|---|
| `subject_id` | FK Subject | renamed from `case_id` |
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

`SourceTier` stays global across strategies — source provenance is a generic concept,
not strategy-specific, unlike the gate *thresholds* applied to it.

`UNVERIFIED` sources may be stored as leads but never count toward the R1 gate and must
never be cited in a script.

### R1 gate

`packages/research/gate.py::check_source_gate(subject_id) -> GateResult`

Passes only when all hold:
1. At least `strategy.min_verified_sources` sources with tier other than `UNVERIFIED`
2. At least `strategy.min_primary_records` with tier `PRIMARY_RECORD`
3. At least `strategy.min_distinct_domains` **distinct** `domain` values among them
   (independence)

The gate's structure — three named conditions, shared code — is reused by every
strategy unchanged; only the numeric thresholds vary, read from the subject's own
`Strategy` row (see "Strategy" above for why thresholds are data while eligibility
scoring is code). Returns structured failure reasons, not a bare bool.

---

## Fact

The reconciled factual layer. Scripts are written from Facts, never from Source text.
This is the architectural reason the output is original expression rather than paraphrase.

| field | type | notes |
|---|---|---|
| `subject_id` | FK Subject | renamed from `case_id` |
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
| `subject_id` | FK Subject | renamed from `case_id` |
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
is legal. No direct assignment. Unaffected by the strategy generalization — it operates
entirely on `PipelineStage` and gate-approval timestamps, never on subject content.

---

## VariationProfile

Enforces R2. Sampled per episode, never reused verbatim.

| field | type | notes |
|---|---|---|
| `strategy_id` | FK Strategy | scopes the similarity-check comparison pool, see below |
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

`strategy_id` is added now, ahead of need: `packages/script` isn't built yet, so nothing
reads this field. It's here so the similarity-check implementation doesn't have to choose
later between a migration and silently comparing structural fingerprints across
strategies that were never meant to be compared — "last 10 published" should mean last 10
for *this* strategy's channels, not across every strategy sharing the product.

### Similarity check

`packages/script/variation.py::check_similarity(profile, recent_profiles) -> float`

Encode the profile as a normalized feature vector, compute cosine similarity against the
last 10 published episodes' profiles **for the same strategy**. Returns the max. Above
`0.85` the sampler resamples, up to 20 attempts, then raises `VariationExhaustedError`.
Do not silently proceed.

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
cannot use. Unaffected by strategy — R6 applies identically regardless of which strategy
an episode belongs to.

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

**Not yet built:** `Channel` (per-strategy platform credentials). `Publication.platform`
is a bare enum for now with no link to a specific credentialed account — fine while there
is exactly one channel per platform, which stops being true once `Channel` lands.
Deliberately out of scope for the Strategy/Subject migration; when it's built,
`Publication` gains a `channel_id` FK and credentials are referenced (Keychain, via
`keyring`), never stored in the database.

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

- `strategy.slug` unique
- `subject.slug` unique, `subject.strategy_id`, `subject.status`, `subject.monetization_tier`
- `source.subject_id`, `source.text_sha256`
- `fact.subject_id`
- `episode.subject_id`, `episode.stage`
- `variation_profile.strategy_id`
- `publication.platform_post_id` unique per platform
- `metric_snapshot.(publication_id, captured_at)` composite
- `job.(status, scheduled_for)` composite
