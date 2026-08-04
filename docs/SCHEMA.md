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

## Claim, ClaimSource

docs/SOURCING.md's claim table -- the reconciled factual layer. Scripts are written from
Claims, never from Source text. This is the architectural reason the output is original
expression rather than paraphrase. Renamed and extended from the old, never-wired-up
`Fact`/`FactSource`: nothing outside `packages/db/models.py` referenced either, so the
rename cost nothing and there was no reason to keep two names for the same concept.

| field | type | notes |
|---|---|---|
| `subject_id` | FK Subject | |
| `statement` | str | one atomic claim, plainly worded |
| `category` | ClaimCategory | subject-matter axis — renamed from `FactType`, same 7 values |
| `claim_type` | ClaimType | epistemic axis — docs/SOURCING.md's `type` field |
| `confidence` | ClaimConfidence | replaces the old float 0–1 |
| `contested_note` | str \| None | how sources disagree; only meaningful when `confidence == CONTESTED`, not DB-enforced |
| `date_anchor` | str \| None | free text, not `date` — see below |
| `narratable` | bool, default `False` | the core invariant — see below |

```python
class ClaimCategory(StrEnum):
    EVENT = "event"
    PERSON = "person"
    LOCATION = "location"
    TIMELINE = "timeline"
    EVIDENCE = "evidence"
    LEGAL_OUTCOME = "legal_outcome"
    AFTERMATH = "aftermath"


class ClaimType(StrEnum):
    FACT = "fact"
    CONTEMPORANEOUS_REPORT = "contemporaneous_report"
    DISPUTED = "disputed"
    INFERENCE = "inference"


class ClaimConfidence(StrEnum):
    ESTABLISHED = "established"
    REPORTED = "reported"
    CONTESTED = "contested"
```

`category` and `claim_type` are deliberately separate axes, not collapsed into one
field: `category` is what the claim is *about*, `claim_type` is *how it's known*.
Collapsing them would lose the ability to ask "show me all evidence claims" independent
of epistemic status.

`date_anchor` stays `str`, not `date`: real historical claims are often only precise to
a month or a season, and forcing a `date` column would mean inventing a fake day for
those. If strict chronological sorting is ever needed (e.g. for the `chronological`
episode architecture below), add a separate nullable `sort_date` alongside this rather
than tightening it.

**`ClaimSource`** — join table (`claim_id`, `source_id`), renamed from `FactSource`.

### The narratable invariant

This is the whole point of the spec: **a narratable claim's sourcing must be exclusively
Tier A.** Not "at least one Tier A source among otherwise-mixed sourcing" — every linked
source, full stop. `packages.domain.enums.TIER_A_SOURCE_TIERS` names exactly
`PRIMARY_RECORD` and `CONTEMPORANEOUS`; Tier B (`RETROSPECTIVE`, `BOOK`, `REFERENCE`,
`UNVERIFIED`) may inform research but may never be cited on a narratable claim, and Tier
C isn't represented in `SourceTier` at all — those sources are excluded at the fetch
layer and never become `Source` rows in the first place.

Enforced at the persistence layer (`packages/db/listeners.py`), not by convention, across
five touchpoints — because there are five different writes that could otherwise put a
narratable Claim into a state where the invariant no longer holds:

1. **`Claim.before_insert`** — `narratable=True` is rejected outright. A Claim can't
   cite a source before it exists (`ClaimSource.claim_id` requires the row already be
   there), so this isn't really a check, it falls out of FK ordering for free.
2. **`Claim.before_update`** — flipping `narratable` to `True` requires at least one
   linked source, and every one of them must be Tier A.
3. **`ClaimSource.before_insert`** — attaching a new source to an already-narratable
   claim is rejected if that source isn't Tier A. Prevents silently degrading a claim
   after the fact.
4. **`ClaimSource.before_delete`** — removing a narratable claim's *last* source is
   rejected. Without this, deleting a claim's only source would leave it vacuously
   "all sources are Tier A" (there being none) while violating the actual requirement
   — at least one Tier A source, not just no bad ones.
5. **`Source.before_update`** — downgrading a source's tier is rejected if it's
   currently cited by any narratable claim. Closes the gap where a claim would
   silently become invalid without anything about the claim itself changing.

All five raise (`NarratableSourcingError`) rather than silently correcting the write:
coercing `narratable` to a value the caller didn't ask for would look like their write
succeeded when it didn't, which is a worse failure mode than a clean rejection.

**Trust boundary, same as everywhere else in this file:** these are ORM-level
guarantees, not raw-SQL-proof triggers. A direct `sqlite3` write against the `.db` file
bypasses all five listeners, the same way it would bypass `Subject`'s scoring or
`Source`'s domain derivation. Nothing here changes that trust model, it just applies it
to a new invariant.

---

## Entity, ClaimEntity

docs/SOURCING.md's entity table — a named person in a Subject's record. Subject-scoped,
not global: the same real person appearing across multiple subjects is out of scope for
this pass (no cross-subject dedup exists). Simpler for now, and not a breaking choice to
revisit later if cross-subject entity reuse ever becomes a real requirement.

| field | type | notes |
|---|---|---|
| `subject_id` | FK Subject | |
| `name` | str | |
| `role` | EntityRole | |
| `living` | bool, **indexed** | gates render — see below |
| `adjudicated` | bool | descriptive only, not wired into anything yet |
| `image_rights` | ImageRights | |

```python
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
```

`living=True` on any entity trips docs/POLICY.md's R8 and blocks render pending review.
(POLICY.md's "Derived engineering requirements" table numbers its own rules
independently of CLAUDE.md's R1–R7 — they collide on numbers without sharing content;
"R8" here is POLICY.md's.) `living` is indexed, not just typed, because it's expected to
be filtered on directly once render gating exists, not just stored. `image_rights=NONE`
blocks that entity from stage 3 shot selection. Neither consuming check is built yet —
these columns exist so they have somewhere to read from once they are.

`adjudicated` is stored but purely descriptive for this pass — it isn't wired into
`LegalRisk` scoring or anything else. What it should eventually gate is an open
question, not a decided one.

**Known gap, not addressed here:** `Subject.living_persons_involved` and `Entity.living`
are now two independent sources of truth for a closely related fact, and nothing keeps
them in sync — a Subject could have `living_persons_involved=False` while one of its
Entities has `living=True`, and nothing will catch that. Deliberately not wiring a
cross-model computation (mirroring how `Subject.monetization_tier` is computed) in a
stage-1-data-layer-only pass. Worth revisiting once something actually reads
`Entity.living` for render gating.

**`ClaimEntity`** — join table (`claim_id`, `entity_id`), mirroring `ClaimSource`'s shape.

---

## Episode

One production run: a specific thesis + architecture + ordered claim selection over a
Subject — not a Subject property. Many Episodes may exist per Subject; this was already
true before docs/SOURCING.md's uniqueness requirement (no constraint ever forced one
Episode per Subject), but it's now the load-bearing reason thesis, architecture, and
claim selection live here rather than on Subject: two users, or the same user twice,
covering the same case are expected to produce different Episodes.

| field | type | notes |
|---|---|---|
| `subject_id` | FK Subject | renamed from `case_id` |
| `variation_profile_id` | FK VariationProfile | |
| `stage` | PipelineStage | current position |
| `gate_a_approved_at` | datetime \| None | script approval |
| `gate_b_approved_at` | datetime \| None | cut approval |
| `structural_fingerprint` | str | hash of the *render*-level variation dimensions (R2) |
| `failed_at_stage` | str \| None | |
| `error` | str \| None | |
| `thesis` | str \| None | human-authored; required before render, not at creation |
| `architecture` | EpisodeArchitecture \| None | docs/SOURCING.md's variation manifest |
| `generation_fingerprint` | str \| None, **indexed** | hash of (thesis, architecture, ordered claim IDs) — see below |
| `uniqueness_check` | UniquenessCheckStatus | result of the (unbuilt) hosted registry check — see below |

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


class EpisodeArchitecture(StrEnum):
    CHRONOLOGICAL = "chronological"
    INVESTIGATION_LED = "investigation_led"
    RECORD_FORWARD = "record_forward"
    MISCONCEPTION = "misconception"
    OPEN_QUESTION = "open_question"
    CONTEXT_FIRST = "context_first"


class UniquenessCheckStatus(StrEnum):
    NOT_CHECKED = "not_checked"
    LOCAL_ONLY = "local_only"
    VERIFIED_UNIQUE = "verified_unique"
    COLLISION_DETECTED = "collision_detected"
```

Stage transitions go through `Episode.advance_to(stage)`, which validates the transition
is legal. No direct assignment. Unaffected by the strategy generalization — it operates
entirely on `PipelineStage` and gate-approval timestamps, never on subject content.

`thesis` and `architecture` are nullable at creation — an Episode exists from `CREATED`,
long before either is chosen — and enforced non-empty/non-null at a render gate check,
not by a `NOT NULL` column. Same treatment `structural_fingerprint` already gets.
`architecture` selects narrative structure in stage 1; it is **not** yet wired to
`VariationProfile`'s render-level dimensions (cold open style, pacing, transitions),
though docs/SOURCING.md says it eventually should be ("architecture selects the visual
grammar and pacing profile in `compose.py`"). That's `packages/script` integration work
that doesn't exist yet — same unbuilt status as `VariationProfile`'s own similarity
check below.

### `EpisodeClaim`

Ordered claim selection: `episode_id`, `claim_id`, `position` (preserves narrative
order), `UniqueConstraint(episode_id, claim_id)`. A row referencing a Claim whose
`narratable` isn't `True` is rejected at insert (`NonNarratableClaimError`) —
`narratable` is meaningless if it can be bypassed one hop downstream at episode
assembly, so the same persistence-layer enforcement approach used for the Claim/Source
invariant above applies here too.

### Cross-user uniqueness: combinatorial, not stochastic

The product requirement: two users (or the same user twice) researching the same
subject must not produce similar scripts, and that guarantee must be **combinatorial**
— thesis × architecture × ordered claim subset — not stochastic. Varying an LLM's
temperature or seed to get different wording over an identical skeleton is not
structural variation; it's docs/POLICY.md's Bucket 1 with extra steps.

`generation_fingerprint` hashes (thesis, architecture, ordered claim ID list) —
deliberately the *input* to generation, never the generated script text. Checking
output-text similarity (or dodging such a check by varying temperature/seed) is exactly
the weak differentiation described above: different wording over the same skeleton is
still the same skeleton. Hashing structured input instead of prose also means only a
hash, never the raw thesis, ever needs to leave the machine — relevant below.

Two different guarantees exist here, at two different strengths:

- **Exact-duplicate floor, enforced now:** `UniqueConstraint(subject_id,
  generation_fingerprint)`. A hard DB-level guarantee against byte-identical
  (thesis, architecture, claim subset) combinations, *within one installation.*
  `generation_fingerprint` is `str | None`, defaulting to `None` and not `""` — SQL
  unique constraints don't exempt empty string the way they exempt `NULL`, and Episodes
  exist from `CREATED`, long before a fingerprint can be computed, so several
  unfingerprinted episodes for the same subject need to coexist without colliding
  against each other.
- **Semantic-similarity check, not built:** two theses that are substantively the same
  idea in different words won't collide on this exact-match constraint. Closing that
  gap is generation-side work (comparable to `VariationProfile`'s own unimplemented
  cosine-similarity check for R2, below) that belongs in `packages/script`, not the
  data layer — the schema stores everything such a check would need (raw thesis text,
  ordered claim IDs), it just doesn't run one yet.

### The hosted registry — not built; schema and seam ready for it

**No cross-installation uniqueness guarantee is possible without a hosted component.**
Two customers each running their own local SQLite database have zero visibility into
each other's installation; a `UNIQUE` constraint only ever sees this machine's own
Episode history. Local-only can widen the combinatorial space (architecture is a 1-in-6
draw, thesis is human-authored high-entropy text) but that's probabilistic breadth, not
a guarantee — "unlikely to collide" and "cannot collide" are different claims, and only
the second is an actual guarantee.

Decision: build for a **thin hosted registry**, not a full backend. The contract, for
whenever `packages/script` exists to call it:

```
check_uniqueness(subject_hash: str, fingerprint_hash: str) -> UniquenessCheckStatus
```

Receives only two hashes — never thesis text, claim data, or generated scripts. Because
`generation_fingerprint` is already computed from structured input rather than output
prose, nothing sensitive needs to cross the network for this to work. **A network
failure must never block a user's work:** if the registry is unreachable, generation
proceeds anyway, `uniqueness_check` is set to `LOCAL_ONLY`, and only the local `UNIQUE`
constraint above actually guarded it. No stub client module exists yet — there's no
caller to wire it into until `packages/script` does, and building one ahead of a real
consumer was a deliberate choice not to make, same reasoning as `Channel`'s publish
adapters.

**Two open product questions, deliberately left unsolved here:**

- **What does `COLLISION_DETECTED` actually trigger?** A hard block forcing
  regeneration (mirroring how `VariationExhaustedError` already refuses to silently
  proceed on R2's similarity check), or just a flagged warning? Not decided — recording
  it now so it isn't a surprise the first time the registry exists and actually returns
  one.
- **What makes two independently-run installations agree they're covering the same
  real-world subject, before a fingerprint registry means anything at all?**
  `subject.slug` is arbitrary per-installation text — one user's
  `hinterkaifeck-murders` and another's `hinterkaifeck-farm-case` would hash
  differently, and the registry would never detect they're the same case. A hash of
  `(strategy.slug, event_year, normalized title)` is the obvious starting point but is
  genuinely fragile against title variation; a canonical external identifier (a
  Wikidata ID, a court case number) would be more robust if one exists for a given
  subject, but nothing here resolves one. This is the hardest part of the hosted
  service and the part most likely to be forgotten if it isn't written down now.

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

**`ScriptCitation`** — join (`script_id`, `claim_id`) recording which claims a script
draws on. A script citing fewer than 8 distinct claims is suspiciously thin; warn.

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

## Channel

A strategy's credentialed account on one platform. Publishing needs to know not just
*which platform* but *which specific account* — a strategy may eventually run more than
one channel on the same platform, which is exactly why `Publication` below references a
`Channel`, not a bare `Platform` value.

| field | type | notes |
|---|---|---|
| `strategy_id` | FK Strategy | which strategy this channel publishes for |
| `platform` | Platform | `YOUTUBE`, `TIKTOK`, `INSTAGRAM`, `FACEBOOK` |
| `display_name` | str | e.g. "Casefile — Criminal Archive" |
| `external_account_id` | str | the platform's own account/channel identifier |
| `credentials_ref` | str | **a reference, never the secret** — see below |
| `is_active` | bool | whether this channel is currently usable for publishing |

`(platform, external_account_id)` is unique — the same real-world account should never
be registered as two different `Channel` rows. `(strategy_id, platform)` is deliberately
**not** unique, for the reason stated above.

### Credentials never live in the database

`credentials_ref` names a macOS Keychain entry (resolved at publish time via the
`keyring` package). This is not a stylistic choice — CLAUDE.md's rule is "no secrets, API
keys, or tokens in the repo, no exceptions," and `data/casefile.db`, while gitignored,
was never designed to reason about as a secrets store: a DB backup or a copied `data/`
directory would leak a stored token in a way the repo's pre-commit hook can't see.
`ChannelCreate`, `ChannelUpdate`, and `ChannelRead` structurally cannot carry a token —
there is no `credentials` field on any of them, `extra="forbid"` turns an attempt to
smuggle one in via `credentials` or `access_token` into a 422, and there is no endpoint
anywhere in this API that accepts or returns credential material. The `keyring`
integration that actually resolves `credentials_ref` at publish time is not built yet;
this column exists so the reference has somewhere to live once it is.

### Endpoints

```
GET   /strategies/{slug}/channels              list a strategy's channels
POST  /strategies/{slug}/channels               create one
PATCH /strategies/{slug}/channels/{channel_id}  partial update (deactivate: is_active=false)
```

No `DELETE` — a channel that's no longer usable gets deactivated, not removed, since a
`Publication` may already reference it. No create/update endpoint accepts `strategy_id`
in the body (it comes from the URL) for the same immutability reasoning as `Subject`.

### Known gaps (tracked here — no separate backlog file exists yet)

- `update_channel` doesn't special-case an `IntegrityError` from a `PATCH` that changes
  `external_account_id` into a collision with another channel's
  `(platform, external_account_id)`. That surfaces as an unhandled 500 today; a 409
  belongs there instead. Untested either way.
- `Publication.channel_id` is a required FK with no factory and no test instantiating a
  `Publication` at all — fine while `packages/publish/` doesn't exist, but it means the
  FK is effectively unexercised. Worth revisiting once publish adapters land, so this
  isn't a surprise the first time something actually inserts a `Publication` row.
- `docs/ARCHIVE-SPEC.md` line 196 still references the old `Case`/`Fact` naming
  (`Case` was already renamed to `Subject`, `Fact` is now `Claim`) — doubly stale, not
  fixed here since it's a different document outside this pass's scope.

---

## Publication, MetricSnapshot

| Publication | type | notes |
|---|---|---|
| `episode_id` | FK Episode | |
| `channel_id` | FK Channel | which credentialed account this went out through |
| `platform` | Platform | `YOUTUBE`, `TIKTOK`, `INSTAGRAM`, `FACEBOOK` |
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

**Still not built:** the publish adapters themselves (`packages/publish/`), the OAuth
connect flow, and the `keyring` integration. `Channel` rows exist and can be listed,
created, and deactivated, but nothing in this codebase can actually post to a platform
yet — `POST /strategies/{slug}/channels` registers an account's *identity*, it does not
connect one. The frontend's Publishing page reflects this literally: an inactive channel
renders as "Not connected" with a disabled Connect button, not a fake connected state.

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
- `claim.subject_id`
- `entity.subject_id`, `entity.living`
- `episode.subject_id`, `episode.stage`, `episode.generation_fingerprint`, `episode.(subject_id, generation_fingerprint)` unique
- `variation_profile.strategy_id`
- `channel.strategy_id`, `channel.(platform, external_account_id)` unique
- `publication.channel_id`, `publication.platform_post_id` unique per platform
- `metric_snapshot.(publication_id, captured_at)` composite
- `job.(status, scheduled_for)` composite
