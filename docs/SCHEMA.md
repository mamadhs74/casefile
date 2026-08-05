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

### Fetch layer (`packages/research/fetch.py`)

`SourceFetcher.fetch_source()` retrieves a URL and persists a `Source` row. Async
throughout (`httpx.AsyncClient`), matching docs/ARCHIVE-SPEC.md's established pattern
for the sibling archive-retrieval package — but not wired into a job queue. `Job`
exists as a table; no worker process reads it yet, so this is a plain awaitable
anything can call directly.

**Order is deliberate, not incidental:**

1. **Tier C blocklist** (`packages/research/tiering.py`) — checked before any network
   request at all, including robots.txt. docs/SOURCING.md: Tier C sources are "never
   read, never ingested," not merely excluded after the fetch. A `frozenset[str]` of
   domains, checked via the same `derive_domain()` used everywhere else (now shared
   in `packages/domain/urls.py` rather than duplicated — see below). Starts sparse,
   expected to grow from real rejections the same way docs/ARCHIVE-SPEC.md describes
   growing its license-fixtures file. Code-reviewed, not runtime-editable.
2. **Idempotent `(subject_id, url)` check** — refetching a URL already fetched for
   this subject returns the existing row, no new request.
3. **robots.txt**, cached per exact host (not the collapsed registrable domain —
   robots.txt is a per-origin document under RFC 9309), **then rate limiting**
   (`packages/research/rate_limit.py`, a generic per-domain minimum-interval throttle
   keyed on the collapsed domain — unlike docs/ARCHIVE-SPEC.md's five hand-written
   per-provider adapters, source fetching hits arbitrary operator-supplied domains,
   so it can't be a fixed table), **then the HTTP GET** (retry with backoff on
   429/5xx only, matching docs/ARCHIVE-SPEC.md; no retry on other 4xx).
4. **Extraction** (`packages/research/extraction.py`) — HTML via `trafilatura`, PDF
   via `pypdf`, content-type sniffed with a magic-bytes fallback. Raises
   `EmptyExtractionError` before anything is persisted if the result is below 25
   words. **This ordering is load-bearing:** archival court records and inquest
   reports are very often scans with no text layer, and without rejecting empty
   extraction *first*, two such failures (two different scans, both extracting to
   `""`) would both hash to `sha256("")` and collide against the constraint below —
   for the wrong reason, "identical empty content," not "identical real content."
5. **Content-hash dedup** — `(subject_id, text_sha256)`, see `Source`'s own
   `UniqueConstraint` below.
6. **Tier assignment** (`packages/research/tiering.py`) — see below. Never Tier A.
7. Extracted text is written to `data/cases/{subject_id}/sources/{text_sha256}.txt`,
   then the `Source` row is persisted.

**Tier assignment: heuristics may write Tier B or `UNVERIFIED`, never Tier A.** The
risk is asymmetric — a source wrongly left at `UNVERIFIED` just sits as an
unclassified lead until a researcher reviews it (harmless, that's Tier B's actual
role even for something that later turns out to be Tier A). A source wrongly
*auto*-assigned `PRIMARY_RECORD` or `CONTEMPORANEOUS` could let a bad source into a
narratable claim, undoing the entire point of the five listeners on `Claim`.
Concretely: a domain on `REFERENCE_DOMAINS` (Wikipedia, other reference wikis) is
tagged `REFERENCE` automatically — detection here is unambiguous and the ceiling is
Tier B regardless, so a wrong guess costs nothing. **Everything else defaults to
`UNVERIFIED`, including `.gov`, court domains, and national archives** — a `.gov`
domain can host a blog post about a case exactly as easily as the court filing
itself, so domain alone never writes a Tier A value. Book-domain detection is
deliberately left unautomated (murkier to detect reliably than Wikipedia; also
defaults `UNVERIFIED`). Promoting a source to Tier A is a plain field update a
researcher makes after review — nothing currently blocks that *upgrade* (only a
*downgrade* away from Tier A while cited by a narratable claim is blocked, per
`Claim`'s narratable invariant above).

**First real use of this path:** `source_7` (`crimearchives.net`'s transcription of a
June 20, 1893 Boston Globe article on the Borden verdict) fetched as `UNVERIFIED`, same
as any other domain the heuristics don't recognize — the automation has no way to know a
modern site is hosting a faithful transcription of a genuine period newspaper. Promoted
to `CONTEMPORANEOUS` by direct review of the content, specifically to test the
claim-extraction prompt against a real contemporaneous source rather than another
disposable Tier B fixture. The upgrade path existed in the design since the tiering
section above was written; this is the first time anything actually went through it.

**`Source.text_sha256` is now unique per `(subject_id, text_sha256)`** — a hard DB
constraint, not just the fetch layer's own pre-check (which exists too, and raises
`DuplicateSourceContentError` naming the existing row rather than a raw
`IntegrityError`). This isn't duplicate-waste prevention: a syndicated copy of the
same article under a second URL would otherwise inflate `check_source_gate()`'s
distinct-domain and verified-source counts, and that gate has monetization meaning —
a gate passing when it shouldn't. `tests/factories.py::make_source` and
`tests/test_api_sources.py::_source_payload` both derive their default
`text_sha256` from `url` now rather than a fixed constant, for the same reason: a
shared constant modeled something that can't happen, two sources with byte-identical
content.

**`robots.txt`, missing vs. unreachable, are different outcomes.** No `robots.txt` at
all (404) is allow-all per RFC 9309. A `robots.txt` that fails to fetch for any other
reason (timeout, 5xx, connection error) is treated conservatively —
`RobotsUnreachableError`, the fetch is skipped, not assumed permitted. Given how
expensive an IP ban from a source you need would be, erring toward caution on the
ambiguous case is the right tradeoff even though it means a flaky robots.txt endpoint
can stall an otherwise-fine fetch.

**Bug found and fixed on the fetch layer's first live run against real sites:**
`RobotsCache._fetch_and_parse()` fetched `robots.txt` without ever passing the
configured `User-Agent` header, so it went out as bare `python-httpx/0.28.x` — a
different identity than the real content `GET` in `fetch.py`, which has always set the
header correctly. `en.wikipedia.org` returned `HTTP 403` on that unauthenticated-looking
robots.txt request specifically, which `RobotsUnreachableError`'s conservative-skip
behavior then (correctly, given what it saw) treated as "don't fetch." Confirmed by
reproducing the 403 through the real code path, inspecting `httpx.AsyncClient`'s default
header set, and confirming the fetch succeeds once the robots.txt request carries the
same `User-Agent` the content request already does — no change to the UA string itself
was needed. Fixed with one line: `robots.py`'s request now passes
`headers={"User-Agent": self._user_agent}`, matching `fetch.py`. `DEFAULT_USER_AGENT`
remains a generic placeholder per its own docstring — still worth a real contact URL
before fetching at scale — but that's a separate, pre-existing item, not what caused
today's failure.

**`derive_domain()` moved to `packages/domain/urls.py`**, shared between
`packages/db/listeners.py` (Source.domain derivation) and `packages/research/`
(blocklist checks, rate limiting). It was a private, duplicated function before;
two independent implementations of "what counts as one domain" drifting apart would
be a real bug, not a style nit — R1's gate counts distinct domains for independence.

### Extraction specificity

Word count alone is not a specificity check. The defect this section addresses is
worse than a hash collision: an extraction failure that returns plausible-length,
non-empty text can enter the corpus as a **valid-looking `Source` on its own, with no
second fetch required to expose it** — `check_source_gate()` would count it, and
nothing before this investigation would have caught it. Three concrete failure modes
were tested directly against the installed `trafilatura` version, not reasoned about
abstractly:

1. **Nav/chrome fallback.** When `trafilatura` can't confidently identify a page's
   main content (e.g. a scan-viewer page whose only real content is an `<img>` with
   no text alternative), its documented behavior is to fall back to extracting
   *something* — nav, header, and footer text — rather than return empty. Tested:
   three different archive record pages (an inquest, a shipping notice, a probate
   record) sharing one realistic site template extracted to **byte-identical
   30-39-word text**, comfortably above the old 25-word floor.
2. **Paywall stubs.** A no-teaser paywall (headline immediately followed by a
   subscribe wall, common on some publications) extracted to text that was 25 of 27
   words identical across two different articles, differing only by a two-word
   headline — one template detail away from an exact collision.
3. **A 200 response with a generic, well-formed error/placeholder page.** Tested: two
   different fake domains serving the same "Service Temporarily Unavailable" page
   extracted to byte-identical text, comfortably above even the raised 40-word floor.
   This is structurally indistinguishable from a real short article — a heading plus
   a prose paragraph inside a semantic content container — so it survives every
   structural signal below. It's also the one case a purely lexical check can't touch:
   the sentence *is* well-formed, grammatical English, it just isn't about anything.

**Adopted:**

- **`favor_precision=True`** on the HTML extraction call. Biases `trafilatura`
  against returning content it isn't confident about. Tested against both nav-fallback
  variants above (light and heavier template): **0 words**, correctly empty, would
  now hit `EmptyExtractionError` at zero new code. Tested against a genuinely short,
  real primary record (a one-paragraph court order, 30-34 words) and a normal
  article: both unaffected, no substantive content lost. Does **not** catch the
  error-page case (case 3) — confirmed directly, it went from 25 to 28 words, still
  well-formed and non-empty, because `favor_precision` reasons about structural
  confidence, not content semantics.
- **`MIN_EXTRACTED_WORD_COUNT` raised from 25 to 40**, not higher. High enough to
  reject most no-teaser paywall stubs outright. The binding constraint against going
  higher is the same short court-order fixture (30-34 words) — a floor tuned to also
  reliably catch heavier boilerplate would reject exactly the terse, legitimate Tier A
  documents this system exists to be able to use. With `favor_precision` handling
  nav-fallback structurally, the floor no longer has to do that job too.
- **Per-domain reference-sample check** (`packages/research/boilerplate.py`,
  `DomainSampleCache`). The only thing that touches case 3, and the strongest evidence
  available for any of the three: on the first fetch from a new host, also fetch the
  **domain root** (not a sibling record page — simpler to derive, and a homepage is
  more likely to be pure chrome by construction), extract it the same way, and cache
  its `text_sha256` — one extra fetch per new host, reusing `RobotsCache`'s exact
  caching shape, not a network request per URL fetched. A target page whose extracted
  text hashes identically to its domain's cached root sample raises
  `LikelyBoilerplateError` rather than being persisted. A failed or empty reference
  fetch degrades to "no reference for this host" silently — this check exists to
  improve confidence, it must never block the fetch it's checking.

  **Also checked, for free: already-persisted `Source` rows from the same domain,
  across *all* subjects, not just the current one.** The per-subject dedup check
  (`_find_by_hash`) only ever looks within one subject's own sources, so the same
  template chrome recurring across two different subjects researching different cases
  on the same domain would be invisible to it — this is exactly the gap a
  domain-scoped (not subject-scoped) query closes, at the cost of one extra `SELECT`,
  no extra network request.

**Investigated and rejected:**

- **Title/H1 overlap.** Has a blind spot exactly where the failure mode lives: in the
  nav-fallback fixture, the page's `<title>` and `<h1>` *were* the generic site name —
  the same text the fallback grabbed — so an overlap check would score this a strong
  match, not a mismatch. This isn't a fixable edge case in the fixture; it's
  structural. The sites most likely to produce a bare scan-viewer page with no text
  alternative (older, low-budget government and court archive portals) are exactly
  the sites least likely to have distinct per-record `<title>`/`<h1>` values —
  SEO-quality titles and this failure mode are anti-correlated. Actively
  counterproductive against case 3: title "Service Temporarily Unavailable" and a
  body describing a service outage are *genuinely on-topic for each other*, which an
  overlap check would score as a good match.
- **Stopword ratio.** Tested directly: nav-fallback text scored **0.13**, real
  article prose **0.39** — looked like a clean separator. But the short court-order
  fixture scored **0.23**, closer to the nav-fallback end than to normal prose,
  because legal and bureaucratic language is inherently more noun-and-term-dense than
  narrative prose. The false-positive risk concentrates exactly on the register Tier A
  documents are written in — a threshold that reliably excludes nav-fallback (0.13)
  would sit dangerously close to, or above, real legal-document language (0.23).
  Rejected for this reason, not a general objection to lexical heuristics. Recorded
  here with the number so this isn't re-proposed without re-deriving the same
  conflict.
- **Link density.** The right idea in principle — nav menus are link-dense, article
  prose isn't — but not computable from anything `trafilatura`'s public API exposes;
  checked both the plain-text output and the lower-level `bare_extraction().body`
  (an lxml tree), and link-tag boundaries are already stripped by the time either is
  available. Getting real link density would mean a second, separate raw-HTML pass
  reaching into `trafilatura`'s internal node selection rather than its public API —
  fragile against version upgrades, for a signal `favor_precision` already covers via
  a different mechanism. Not worth the coupling.

**Known limitation, not solved:** case 3 (a 200 response with a generic error page) is
**mitigated, not solved**. The domain-reference-sample check only catches it when the
error page happens to match that domain's cached root sample, or an already-fetched
`Source` from the same domain — both real, useful signals, neither exhaustive. A
domain whose root page extracts to something different from a given broken page's
error text (a very plausible outcome — many error pages are served by a CDN or WAF
layer entirely separate from the origin site's actual homepage) slips through
untouched. No further check exists for this today.

### Product-level finding: Tier A material may not exist on the open web for the cases this strategy targets

`SourceFetcher.fetch_source()` was run for the first time against five real, live
URLs, chosen to span the shapes docs/SOURCING.md describes: a Wikipedia reference
article, two long-form true-crime retrospectives, and two real court-opinion PDFs
(fetched purely to exercise the PDF path and stress-test length — unrelated modern
cases, not connected to any real subject). All five fetched successfully once the
robots.txt bug above was fixed. Word counts ranged 989–4,006, confirming the fetch and
extraction layers work correctly end to end against real sites and real PDFs, not just
the synthetic fixtures in `tests/test_fetch.py` / `tests/test_extraction.py`.

**None of the five is Tier A.** The two retrospectives are Tier B at best (blog/media
content, not primary or contemporaneous record); Wikipedia is `REFERENCE`, explicitly
barred from ever being a claim's source per docs/SOURCING.md; the two court PDFs are
real primary records, but for an unrelated present-day case, used only as length
fixtures. For the actual subject this run targeted — a 1922 Bavarian farmstead
murder — Tier A means the original German-language police and inquest records. Those
are very unlikely to be sitting on the open web at a fetchable URL at all: a
hundred-year-old rural German criminal investigation's primary paperwork is the kind of
material that lives in a Bavarian state or district archive, not indexed by a search
engine, not scanned and hosted anywhere `SourceFetcher` can reach with a URL.

**This is the same shape of problem `experiments/slice_01/FINDINGS.md`'s "archival
photo resolution is a real ceiling" finding identified for imagery**, one layer over:
that finding is about *usable resolution* for a well-documented old case;
this one is about *fetchable existence* for its primary sourcing. Both say the same
thing about "well-documented" as this strategy's median case, not its edge case —
the record survives, but not always in a form this pipeline's automation can reach on
its own. `SourceFetcher` is not the gap; it worked exactly as designed against every
URL it was given. The gap is upstream of fetching: **subject selection needs to weigh
whether Tier A material is realistically obtainable by URL at all**, not just whether a
case is well-documented and legally resolved. A case whose only surviving Tier A record
is a physical archive box requires either a research step this pipeline doesn't have
yet (a real records request, or a researcher transcribing/scanning it by hand and
feeding the result in as a `Source` some other way than `fetch_source()`), or it isn't
actually eligible for R1's gate no matter how much retrospective writing exists about
it. Not a bug to fix in the fetch layer — a criterion missing from how subjects get
chosen in the first place.

**A third failure mode, distinct from the two above and from the robots.txt bug already
fixed: material that demonstrably exists online and is indexed, but is walled off by the
host's own anti-bot infrastructure, not by anything wrong in this codebase.** Investigated
while looking for a genuine Tier A/contemporaneous test document for the claim-extraction
prompt (see below): `famous-trials.com` and `lizzieandrewborden.com` — the two sites most
likely to host verbatim inquest testimony for a real historical case — both sit behind a
Cloudflare JS challenge; a plain request gets a challenge page, not content, regardless of
`User-Agent`. `loc.gov` (Chronicling America's current home, after a domain
consolidation) is worse: a real request with a proper descriptive `User-Agent` gets a
flat `403` on the article page, the OCR text endpoint, *and* `robots.txt` itself —
confirmed through the actual fetch layer, not just `curl`. This is not the Wikipedia
case: that was fixable because the bug was ours (a missing header on our own request).
This is not fixable the same way, and **this project will not build the workaround** —
UA spoofing, headless-browser rendering, or any other bot-wall evasion is out of scope on
purpose, not for lack of a mechanism. Three distinct reasons a real Tier A source can be
unreachable now exist as documented findings: our own bug (this section, fixed), doesn't
exist on the open web at all (Hinterkaifeck's German archival records, above), and exists
but is deliberately gated against exactly this kind of automated access (this paragraph,
not something to route around).

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

**`ClaimSource`** — join table (`claim_id`, `source_id`), renamed from `FactSource`, plus
`quoted_span`, `span_start`, `span_end` (all `NOT NULL`) — see "Claim extraction" below.

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

### Claim extraction (`packages/research/claim_extraction.py`)

Turns a persisted `Source`'s text into `Claim`/`ClaimSource` rows. Every claim it
creates is `narratable=False` — set explicitly in this code, not just relied on from the
`Claim.before_insert` listener above, same belt-and-suspenders posture as everywhere
else in this layer.

**Provider interface, deliberately minimal.**
`packages/research/llm_provider.py` defines one `Protocol`
(`ClaimExtractionProvider`, a single `extract_claims(source_text, source_tier) ->
list[ProposedClaim]` method) and nothing else calls a provider SDK directly.
`packages/research/gemini_provider.py` is the one implementation today, using Google AI
Studio's free tier — no API credit purchased yet, the 1M-token context window takes a
long filing in one call, structured output against a JSON schema is supported, and it
costs nothing while the project isn't yet paying for inference. Free-tier providers have
a documented history of silently deleting or replacing models, which is exactly why this
is behind an interface at all: swapping to a paid provider later, if the free tier
disappears or the quality bar needs to move, is a new class satisfying the same
`Protocol` plus a config change — not a rewrite of `claim_extraction.py`. One interface,
one implementation; not built out further than that until a second implementation
actually needs more.

**Verifiability: verbatim quote, located by code, not emitted by the model.** The
model returns `quoted_span` — a claimed verbatim copy of the exact passage supporting
its assertion — never a character offset; asking a model for raw character positions in
arbitrary-length text isn't something LLMs can do reliably. `claim_extraction.py` then
locates that string in the source text and computes `span_start`/`span_end` from the
match. A quote that isn't located is rejected before persistence, unconditionally. This
is the primary defense against a hallucinated citation, and it matters more with a
smaller free-tier model, not less — a smaller model is more likely to paraphrase,
embellish, or invent a citation than a frontier one, and this check is exactly what
catches it. Located spans over `MAX_QUOTED_SPAN_CHARS` (800) are also rejected — a
"supporting passage" longer than that isn't something a reviewer can check in seconds,
which is the entire point of storing it.

**Matching normalizes whitespace only; every other character must match literally —
this was not the first version, and the first version was wrong.** The original design
required an exact byte substring, no normalization at all, on the reasoning that
normalizing anything would let a near-paraphrase slip past as a match. Tested against a
real court-opinion PDF, that rule turned out to reject nearly everything: `pypdf`
preserves the source PDF's physical line breaks as literal `\n` characters, so any quote
spanning even one line-wrap in the original document contains a mid-sentence newline no
model reproduces (nor should it — reproducing a column-width line-wrap position isn't
more faithful quoting, it's reproducing a rendering artifact). Since every substantive
sentence in a paginated document is longer than one line, this meant every substantive
claim was rejected and only a single one-line filing-date stamp survived — a systematic
bias against exactly the sentences an episode would use, discovered by running the
pipeline against a real PDF and noticing the one surviving claim was trivia while every
rejected one was substance. Confirmed directly: comparing the model's rejected quotes
against the source character-by-character showed the words, order, and punctuation
matched in every case — the only difference was `pypdf`'s embedded line-wrap newlines.

The fix: `_locate_span()` builds a regex from the quote's whitespace-delimited tokens
(each escaped, joined by `\s+`) and searches it against the source text directly, so
`span_start`/`span_end` come from the real match — no separate normalized copy, no
offset remapping. A run of whitespace in the quote matches any run of whitespace in the
source; every non-whitespace character still has to match exactly, so a substituted
word, an invented clause, or reordered content still fails the same as before. The
stored `quoted_span` is the actual matched substring from the source text (embedded
newlines included, if any), not the model's normalized version — `ClaimSource.quoted_span
== source_text[span_start:span_end]` always holds, which also means it stays
byte-findable against the source file itself.

**Checked against an HTML source too, not assumed fixed everywhere.** `trafilatura`
does not have this problem the same way: its line breaks land at paragraph/sentence
boundaries, not at arbitrary column width mid-sentence, so a model's one-sentence quote
rarely crosses one. Confirmed empirically on a real fetched article — all 7 claims
extracted matched with zero embedded newlines in any of the located spans, meaning the
byte-exact rule would have passed every one of them too. The whitespace-normalization
fix is a no-op on this source, not merely harmless: nothing about it was needed here.
This was a PDF-extraction-specific defect, and the fix targets exactly that without
changing behavior on HTML sources.

**`RejectedClaim` stores the attempted `quoted_span`, not just the rejection reason.**
The original version only recorded why a candidate was rejected, which meant diagnosing
this exact defect required making fresh, non-deterministic API calls to reconstruct what
the model had actually proposed — the original run's rejected quotes were simply gone. A
rejected claim is the thing most worth being able to inspect later, and it was the thing
being discarded most completely.

**This makes citations structurally verifiable, not semantically verifiable — and
that boundary matters more than it sounds.** The mechanism proves a claim's quote
provably exists, verbatim, where the claim says it does. It cannot and does not prove
that the claim actually follows from that quote — a citation can point at a real
passage and still draw the wrong conclusion from it, and no automated check here catches
that. That's a human's job at review time, not something this system does for them. Worth
stating plainly because it's easy to later assume the offset mechanism buys more safety
than it does.

**`claim_type` is constrained to `{FACT, CONTEMPORANEOUS_REPORT, INFERENCE}` at the
provider's own structured-output schema** — `DISPUTED` is never a valid extraction
output (defensively re-checked in `claim_extraction.py` too, in case a provider's schema
enforcement is ever weaker than expected). A single source's text cannot establish that
sources *disagree*; that requires comparing claims across sources, which is
`reconcile_facts`' job (CLAUDE.md's pipeline diagram) — a stage that doesn't exist yet.
The prompt also passes `source.tier` as plain-language context, and instructs the model
to prefer the more cautious classification when unsure, in this order least-to-most
confident: inference, contemporaneous_report, fact. Text alone systematically
over-classifies confidently-worded period reporting as `FACT`; a newspaper's unhedged
sentence is still a report, not an adjudicated fact, and the source's own tier is what
lets the model apply that asymmetry.

**`confidence` is derived mechanically from `claim_type`, not asked of the model as a
second free choice:** `FACT → ESTABLISHED`, `CONTEMPORANEOUS_REPORT → REPORTED`,
`INFERENCE → REPORTED`. SOURCING.md's `type` and `confidence` fields read as if they
vary independently, but `type: disputed` and `confidence: contested` both describe the
same underlying situation — sources disagreeing — which extraction can't observe from
one source's text any more than it can observe `DISPUTED`. Fixing the mapping shrinks
the model's judgment surface by one axis instead of asking it to keep two overlapping
fields consistent; `CONTESTED` (like `DISPUTED`) is reserved for the same future
reconciliation stage.

**Known risk: `claim_type` classification quality with a free-tier model.** This is the
single field SOURCING.md says matters most — "most of what separates responsible true
crime from the rest" — and it's also the judgment call most sensitive to model
capability: distinguishing an adjudicated fact from confidently-worded period reporting
from a reasonable inference is a nuanced call, and a smaller free-tier model is the most
likely place in this whole pipeline for that judgment to be wrong in the dangerous
direction (`CONTEMPORANEOUS_REPORT` or `INFERENCE` misclassified as `FACT`). The
verbatim-quote check catches a hallucinated *citation*; it does not catch a real,
correctly-quoted passage assigned the wrong epistemic status. Worth spot-checking a
sample of real extraction output against a paid frontier model before trusting this at
volume — not done as part of this piece.

**This risk materialized on the first real run, and was fixed with a prompt change, not
a validation change.** Against `source_5` (the real court-opinion PDF), the model
flattened a party's argument ("On appeal, Long argues...") and a witness's testimony
("...minor child testified that...") to `fact`, correctly keeping the court's own
holdings ("We hold...") and plain procedural statements as `fact`. The prompt's original
tier-based guidance didn't help, because it targets a different problem — how much to
trust the *source document* as a whole — while this error was about content *inside* an
authoritative document. Fixed by adding a subject-of-the-verb check to
`_SYSTEM_INSTRUCTION` (`gemini_provider.py`): a party or witness as the subject
(argues, testified, alleged, claimed) is `contemporaneous_report` regardless of the
source's tier; the court itself as the subject (holds, finds, rules) is `fact`. Includes
worked examples drawn from the real document, since abstract instructions were
insufficient the first time.

**Checked for non-determinism, not assumed stable.** Ran `source_5` extraction twice
after the fix, `--force`, no other change between runs. Every passage the model
extracted in *both* runs got the identical `claim_type` both times, including both
previously-misclassified ones (the argument and the testimony both landed
`contemporaneous_report` in both runs; both court holdings stayed `fact` in both). The
only variation between runs was in *candidate selection* — the filing-date claim was
proposed in one run and not the other — not in classification of a passage once
selected. Recording this explicitly because "we checked for non-determinism and it held"
is exactly the kind of claim that gets assumed true later without ever having been
verified; here it was verified, on this date, on this source, and this is what running
it twice actually showed.

**Tested against a Tier B/`unverified` HTML source too: uniform `contemporaneous_report`
is very likely correct, not degenerate.** Every claim extracted from a retrospective
article (`source_6`), across two runs, came back `contemporaneous_report` — never `fact`.
Argued both ways before concluding this is the right answer: a source with no
adjudicative or first-hand standing structurally cannot establish anything as fact
regardless of how mundane the content is (`Source.tier` already caps this by design, in
the tier-based half of `_SYSTEM_INSTRUCTION`), and since a Tier-B-only claim can never
become `narratable` under the one-`ClaimSource`-per-claim design above, the classification
has no live downstream consequence for this claim either way. Not treated as a defect.

**Selection bias against contested content: suspected self-inflicted, tested, result is a
three-way split by passage, not a single fix or a single failure.** Across two runs on
`source_6` (a retrospective article), `inference`
was never emitted once, and the source's own competing-theory passage — "some theories
claim Karl Gabriel had not actually died..." — was not extracted at all. Promoting
`source_7` to `CONTEMPORANEOUS` and running it twice made the pattern unambiguous:
zero of four contested passages (a disputed burned-dress theory, contradictory police
testimony, a disputed note, a ridiculed alibi) were extracted across two runs, on a
source chosen specifically because it's dense with exactly this content — a *selection*
problem, not a *labeling* one; the model wasn't miscategorizing this material, it was
declining to propose it as a claim at all.

Before filing that as an open question, checked whether the prompt itself was causing
it. `_SYSTEM_INSTRUCTION` says "do not invent claims not supported by the text," ranks
omission-by-caution as the safe direction, and warns against padding the list —
language written entirely to suppress hallucination, with no thought given to whether it
would also read, to a cautious model, as a reason to skip "Knowlton ridiculed the
barn/hayloft story" on the theory that the barn story's truth is unverified. That
conflates two different things: whether the *underlying claim* is true (unverified, and
rightly so) and whether the *fact that someone made the claim* is supported by the text
(it plainly is, right there in the source). The hallucination-suppression language never
drew that line, so there was no reason to expect a cautious model to draw it either.

**Tested, not just reasoned about.** Added an explicit paragraph distinguishing
"contested" from "unsupported," stating that a reported argument or dispute is itself a
directly quotable fact about the record extractable as `contemporaneous_report` or
`inference`, with the barn/hayloft passage as a worked example. Also fixed a separate,
concretely-observed bug in the same pass: `"Foreman-Not guilty."` had been `fact` in one
run and `contemporaneous_report` in another, identical span both times — the
subject-of-the-verb examples covered a court's holding but not a jury's verdict, which is
exactly as adjudicative. Re-ran `source_7` twice after both changes:

- The jury-verdict fix worked cleanly: `fact` in both runs, no more flip.
- The contested-content fix produced **one out of four**: the barn/hayloft passage —
  the one used as the prompt's own worked example — was extracted as
  `contemporaneous_report` in both runs. The burned-dress theory, the contradictory
  police testimony, and the disputed note were still not extracted, in either run.

**Before filing this as an open question, ran a second experiment specifically designed
to separate two hypotheses the first result couldn't distinguish:** H1, a genuine
capability limit on analytically-embedded contested content; versus H2, the model simply
extracts whatever the prompt happens to demonstrate, meaning a better-chosen example
would fix it. The test: swap the worked example from the barn/hayloft passage to the
burned-dress passage — same instruction, one variable changed — and re-run `source_7`
twice again.

```
                            barn ex. (run C)  barn ex. (run D)  dress ex. (run E)  dress ex. (run F)
barn/hayloft                report            report            report             report
burned dress                --                --                report             report
contradictory testimony     --                --                --                 --
disputed note                --                --                --                 --
```

**Neither hypothesis alone fits.** The clean H2 prediction — barn/hayloft stops once it's
no longer demonstrated — is false: it kept extracting correctly in both runs after being
removed from the prompt entirely. That rules out pure pattern-matching-the-example as the
whole story. But burned-dress is the opposite: absent in both runs where it wasn't the
example, present in both runs where it was — real, clean example-sensitivity, just not on
the passage that made it look that way originally. And the remaining two — contradictory
police testimony, the disputed note — were extracted in **zero of four runs**, regardless
of which example the prompt carried.

The honest reading is a three-way split, not a single answer: **barn/hayloft is within
the model's reach from the general instruction alone** (it's short, one named speaker,
one self-contained quotable question — structurally the easiest of the four).
**Burned-dress needs a worked example to reach reliably** (longer, causal/explanatory,
still one named speaker). **Contradictory testimony and the disputed note have not
succeeded under any tested condition** — both are embedded in the reporter's own
analytical voice rather than built around one named speaker's statement, the "who is the
subject" question the whole rule is built on doesn't cleanly apply, and neither has yet
been tried as the demonstrated example itself. That last gap means H1 isn't confirmed for
those two either — only that the two interventions tried so far don't reach them.
Recording this as three-way, not as "H1" or "H2" — collapsing it into either would claim
more than four data points across two passages actually support.

**A third swap, chosen to control for length: the disputed note in place of the
burned-dress example.** Same instruction, one variable, same source, two more runs.
Picked specifically because it's shorter and more self-contained than the contradictory-
testimony line, so a failure here can't be blamed on passage length or embeddedness the
way it could for that one. Full table across all three swaps:

```
                            barn ex. (C)  barn ex. (D)  dress ex. (E)  dress ex. (F)  note ex. (G)  note ex. (H)
barn/hayloft                report        report        report         report         report        report
burned dress                --            --            report         report         report        --
disputed note                --            --            --             --             --            --
contradictory testimony     --            --            --             --             --            --
```

**The disputed note did not extract even as the literal demonstrated example — the
cleanest negative result of the three swaps.** Barn/hayloft generalized past being the
example; burned-dress needed demonstration but mostly worked once given it; the disputed
note failed under the single most favorable condition tested. That's evidence the
"named speaker" framing isn't the full explanation either, though: the worked example
written for it followed the identical "He [Knowlton] did X" pattern as burned-dress and
barn/hayloft, pronoun-referenced back to the same speaker two paragraphs up. What
actually differs is that "the story of the note, its non-confirmation and importance to
the case" doesn't state what was disputed — it's a compressed reference that assumes the
reader already knows the note's content from elsewhere, where the other two passages
name a concrete claim outright ("she wore the Bedford cord and burned it," "her being in
the hay loft"). This may be a fourth explanation (the passage doesn't state enough for a
concrete assertion to be built from it) sitting alongside the original two, not proof the
speaker hypothesis was wrong — three swaps on one document can't separate them further.
Stopping here, as intended: not attempting a fourth example, and not turning this into a
general theory of what extraction can and can't reach. What's confirmed is narrower and
more useful than either — one real capability boundary exists somewhere in this
neighborhood, its exact shape isn't pinned down, and no single prompt change closed it
for all four passages tested.

`_SYSTEM_INSTRUCTION`'s worked example is set to the **burned-dress** version, reverted
from the disputed-note version the last run left it on. Leaving the note example in place
was not the neutral choice it looked like: of the three, it's the one that demonstrably
never worked, not even for itself, across two runs as its own literal demonstrated
example. Shipping it wasn't avoiding a judgment call, it was shipping the worst-performing
option by the only evidence collected. Burned-dress is kept instead for a narrower reason
than "it scored highest": it's the one passage where swapping the example in and out
visibly changed the outcome — absent when it wasn't demonstrated, present when it was.
That's the one case where demonstration provably had an effect, which makes it the
clearest evidence-backed example to actually ship, not a stand-in for "best."

**Re-extraction of a `Source` that already has any linked `Claim` is a no-op unless
`force=True`.** Extraction is not deterministic — the same source run twice will not
produce the same claims — and a prior claim may already be `narratable=True` and cited
by a published episode's `EpisodeClaim`. `force=True` never deletes or merges; it adds a
second batch of candidate claims alongside the first, for a human to reconcile.
Resolving overlap between batches is a review job, the same posture as every other place
this system refuses to auto-correct instead of raising or asking.

**Known gap, real now, not hypothetical: iterating on the prompt this way accumulates
batches with no cleanup path.** Validating the whitespace-matching fix and then the
claim_type prompt fix against the same real source (`source_id=5`) — each a legitimate
reason to re-run — left it with **4 separate batches and 17 total claims** for what a
reviewer actually wants to see as one clean set. Nothing in this system deletes,
supersedes, or marks a batch as superseded by a later one; every batch just accumulates
next to the others, correct ones and since-fixed ones alike, and a human has to reconcile
them by hand with no tooling to help. This is exactly the design tradeoff described
above (never auto-delete or auto-merge, because a claim might already be cited) — it's
the right tradeoff for a claim already in use, but it has a real cost during ordinary
prompt iteration that nothing currently mitigates. Not building a fix now; recording that
one is needed once this moves past one-off manual validation runs.

**Exactly one `ClaimSource` per claim.** A claim built from two different sources is
out of scope for this module — the many-to-many `ClaimSource` table can represent it
(one row per supporting source, each with its own span), but nothing here writes more
than one, because that kind of synthesis is reconciliation's job, not a single-source
extraction pass's.

**Failure modes:** an extraction returning zero claims is valid (a source can genuinely
have no extractable facts) but flagged for operator attention, not raised, when the
source is Tier A — a Tier A source producing nothing is more surprising than a Tier B
one. A truncated model response (an unusually claim-dense source hitting the output-
token ceiling) gets exactly one retry at a higher ceiling before the whole extraction
attempt for that source fails cleanly, with nothing partial persisted.

`scripts/extract_claims.py` runs extraction against a single `Source` at a time — no
batch/queue mode, deliberately: there's no job queue wired up yet, and the first real
run against a real Gemini response is exactly the point a human should look at output
before it touches more than one row. Supports `--dry-run` (runs every validation step,
persists nothing) and `--force`.

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
