# casefile — full handoff

Repo: `github.com/mamadhs74/casefile` · Local: `~/dev/casefile` · Machine: MacBook Air, 8GB M-series
Built with Claude Code CLI. This document is written to be pasted into a fresh session.

---

## 1. What I'm building

An app that produces documentary-style video content and publishes it across social platforms,
where everything it produces is monetizable. I run it myself and may sell it later.

I pick a case; the app does research, script, voiceover, subtitles, shot sequencing, Ken Burns
motion, thumbnails, copyright-free music, upload, and analytics.

Three strategies, each with its own YouTube, TikTok, Instagram and Facebook presence:

1. True crime / horror — built first
2. Celebrity news
3. Film and TV news and trivia

The UI should be genuinely good — colorful, responsive, pleasant.

---

## 2. The constraint that shapes everything

Monetization is a hard requirement. Full detail in `docs/POLICY.md`. Short version:

YouTube's July 2026 inauthentic-content policy disqualifies channels for generic, repetitive or
template-based content, and for off-putting content chasing views. True crime sits near the second
by default. **Enforcement is channel-level** — one bad batch contaminates videos already earning.

The policy is tool-agnostic. What's targeted is **interchangeability**: output that could swap
places with other output unnoticed.

Consequences, and these are the load-bearing design decisions of the whole project:

- Episodes must be **structurally distinct**, not just topically distinct.
- `Episode` carries a human-authored **thesis** and a selected **narrative architecture**, and
  claims are selected per-episode.
- Two customers researching the same case must **not** get similar videos. That uniqueness is
  **combinatorial** — thesis × architecture × claim subset — **not stochastic**. Raising temperature
  produces the same episode with different words, which is the same failure.
- Scripts are written from a **structured claim table, never from source prose**. This is a
  copyright decision and a policy decision at once.

`POLICY.md` quote that matters: *"the pipeline must not be capable of emitting a large volume of
structurally similar episodes. Rate limiting and variation are safety features, not product
limitations."*

---

## 3. How I want to work

- Two tiers for whether to propose before touching anything, per `CLAUDE.md`:
  - **Tier 1 — write it, then show the diff. No proposal step.** New standalone
    scripts that add no logic, read-only queries, test additions, doc edits, type
    annotations.
  - **Tier 2 — propose first, wait for confirmation.** Anything touching
    `packages/db/models.py`, `listeners.py`, `gate.py`, `tiering.py`, `Strategy`
    thresholds, migrations, or any write to `data/casefile.db`.
  - If unsure which tier, it's Tier 2.
- Tell me where a spec is **underspecified** rather than filling the gap silently.
- **Flag problems instead of working around them.**
- **Test claims empirically rather than reasoning about them.** This has caught several real
  defects, including in your own tests.
- I'm not a strong developer. **Exact commands, one per line, no inline comments.**
- Corrections as copy-paste blocks. Git commands one per line.

`CLAUDE.md` conventions: never delete failing tests, never widen types to suppress errors,
senior-developer commit style with a banned-word list.

---

## 4. Stack and shape

- Backend: FastAPI / SQLModel / SQLite, 19-table schema
- Frontend: React / Vite / TypeScript
- Media: Azure Neural TTS, faster-whisper forced alignment, ffmpeg render with libass subtitle
  burn-in
- LLM: Gemini free tier behind a provider interface
- Tests: **355 passing**, mypy strict clean, ruff clean

**Gemini free tier is 20 requests/day/project.** Two calls per source (claims + entities), so ten
sources a day, shared with every dry-run and prompt experiment. This is a real constraint on every
session — never retry a failed run without deciding to spend the quota.

---

## 5. What is built

**Media pipeline**, validated end to end in `experiments/slice_01`: 8.1 min render for a 20-minute
episode static, 14.0 min with Ken Burns.

**The seam between `packages/script` and the render path has now actually been crossed, once.**
A real `SectionedScript.text` (the success-path fixture's output) was pushed through
`experiments/slice_01`'s narrate → align → shots → compose chain with zero code changes to
either side — Azure TTS, faster-whisper alignment, ffmpeg render, real subtitle burn-in, all
against genuine `generate_script` output for the first time.
`experiments/slice_01/output/slice_delivery_casefile_seam_test.mp4` (19.3s, 1920x1080,
h264/AAC). Confirmed the seam works; confirmed nothing else does yet — no claim-to-image
mapping exists (the render used the unrelated Hinterkaifeck stand-in photos, since no other
images exist anywhere), no music, no thumbnail. One tracked fixture
(`experiments/slice_01/work/subs.ass`) was overwritten mid-test and restored via `git
checkout` immediately after; everything else touched is gitignored. In short: the render
path works end to end; the imagery has no relationship to the narration.

**Stage 1 data layer**, both halves:

*Claims* — `Claim`, `Entity`, `Episode` with thesis, architecture, `generation_fingerprint`. The
**narratable invariant** (a claim citable in an episode must have exclusively Tier A sourcing)
enforced across five persistence-layer listeners. Source fetch: retrieval, tier assignment,
robots.txt compliance, HTML and PDF extraction (trafilatura / pypdf). Claim extraction working
against real sources.

*Entities* —

- `Entity.living` is **tri-state** (True/False/None), not defaulted False. None means unreviewed.
  R8 fires when living IS NOT False.
- `living_evidence` is a located span from a Tier A source, verified by code, plus an `EntityMatch`
  row proving that source is about that entity. Enforced across three listeners raising
  `LivingEvidenceError`.
- Consequence: creating an Entity and evidencing its living status are **always two separate writes**.
- `EntityMatch` persists per-source match decisions with located `identifying_span` and
  `match_rationale`, so wrong merges are inspectable.
- `entity_extraction.py`, `gemini_entity_provider.py`, `extract_entities.py` CLI.
- `living` never machine-set. `image_rights` hardcoded NONE. `adjudicated` hardcoded False.

Channels exist as schema only, no OAuth.

**Script generation** — steps 1 and 2 of the build are done. `generate_script(session,
episode_id, *, min_claim_count=40)` takes `episode_id`, not `subject_id` plus a raw
claim-id list; thesis, architecture, thesis-bearing flags, and cold-open selection all
come off `Episode`/`EpisodeClaim`. Enforces the render gate (rule 8 — closes finding
#13 at generation time, not at persistence), rules 6 and 7 (thesis-bearing count 5–10,
total claim count ≥ 40, the latter injectable so tests don't need 40 real rows), a
per-claim `narratable` re-check, and cold-open validation (must be set, must exist,
must be in the episode's claim set, must be thesis-bearing — four named errors).

It now returns `SectionedScript` (six named fields, plus a `.text` property), not a bare
`str`. Section allocation reads `Claim.section` — `GROUND`/`RESOLUTION` go to their named
sections, null goes to Sequence, and the untagged count is reported, never treated as an
error. Rule 4 (section word counts within ±15% of budget, derived from
`VariationProfile.narration_wpm` per `docs/ARCHITECTURES.md` §2, not a hardcoded rate) is
computed and reported on the return value, not enforced — concatenation can't hit a word
target, so raising on it would make this function permanently unable to succeed until
step 3's composition exists. Return emits `Episode.thesis` verbatim as a visible
placeholder, since real paraphrase needs that same composition.

**Step 3 (composition) is now built.** `composition_provider.py` defines the
`CompositionProvider` Protocol (`ClaimForComposition`, `ComposedSection`,
`CompositionProviderError`/`TruncatedCompositionError`); `gemini_composition_provider.py`
implements it against the real Gemini API but **has never been executed** — see §7 finding
#30. `composition.py` is the architecture-agnostic orchestration layer
(`compose_section_text`); rule 4 stays checked-and-reported, not enforced, no automatic
retry. `chronological_composition.py`'s `compose_episode(session, episode_id, provider)` is
the async entry point wiring composition into the `chronological` generator.

Wiring is option B: `generate_script` stays synchronous and behaviorally unchanged — every
one of its checks still runs, and runs first, before any provider call. `SectionedScript`
gained additive per-section claim lists (`cold_open_claim`, `ground_claims`,
`sequence_claims`, `resolution_claims`, all `ClaimForComposition` rather than raw `Claim`,
since `thesis_bearing` lives on `EpisodeClaim` not `Claim`) so `compose_episode` reads the
allocation `generate_script` already did instead of redoing it. Call count is 2–4 per
episode: Sequence and Return always (Sequence can never be empty — the cold-open claim is
always appended to it; Return's paraphrase task needs a call even with no claims), Ground
and Resolution only when `generate_script` put a claim in them.

All of this is tested against a local fake provider only. Zero real Gemini calls spent
building it.

**Roughly 28% of the full vision.**

---

## 6. What is not built

- Shot sequencing, image sourcing, `image_rights` ever leaving NONE
- Thumbnails, music
- `packages/publish/` — no OAuth, no upload adapters, nothing publishes
- Analytics, job queue
- Strategies 2 and 3
- The good UI
- Cross-source **reconciliation** — the stage that would produce DISPUTED claims

---

## 7. Findings ledger

All of these are recorded in `docs/SCHEMA.md`. **None are fixed** except where noted.

### Entity extraction

1. **No participation bar on entity creation.** Analogies and aphorisms become entities. From a
   Lizzie Borden article: Burdell, Carlyle Harris, Dr Buchanan, Rufus Choate, Beecher — all
   rhetorical comparisons, none participants, all created as `Entity` rows with roles.
2. **`role` has no sourcing bar and no participation bar.** Lizzie A. Borden was assigned SUSPECT
   from a span reading "Miss Lizzie A. Borden is Acquitted". Prosecutor, defense counsel and judge
   all collapsed to INVESTIGATOR — `EntityRole` has no legal-role values.
3. **`identifying_span` is not required to isolate one person.** Two entities cited the identical
   span "cases of Carlyle Harris and Dr Buchanan". Recurred on a second subject.
4. **`identifying_span` is not required to contain the evidence its own `match_rationale` reasons
   from.** Span was "young Cäzilia had torn out tufts of her hair"; rationale argued from
   "the 7-year-old daughter of Viktoria Gabriel". Span + rationale is not a self-contained audit
   record.
5. **Rejection path has produced zero rejections across four real runs.** Only ever exercised by
   stub-provider unit tests.
6. **Source-faithful name variants won't match canonical forms.** The prompt asks for the name as
   it appears in the source. Nothing normalizes or fuzzy-matches.
7. **Match rationales are templated per-run.** All rationales in one run share one sentence shape.
   Not wrong, but hard to audit at scale.
8. **`fetch.py`'s domain-duplicate check is unscoped by subject** (`fetch.py:174`,
   `_find_domain_wide_duplicate()`). The same real article cannot be fetched into two subjects.
   Legitimate cross-subject reuse is currently impossible.
9. Entities created outside extraction have no `EntityMatch`, so they're invisible to matching.
10. Order-dependence: processing sources in different orders can produce different entity graphs.
11. Known-entity prompt context grows unbounded per subject.
12. All listeners fire on ORM flush only. Bulk UPDATE bypasses them.

### Documentation asserting enforcement that doesn't exist

13. **The thesis render gate is partially closed.** `generate_script()`
    (`packages/script/chronological.py`) now enforces it at generation time — raises if
    `Episode.thesis` is empty or `Episode.architecture` is null, before any claim is queried. It
    still doesn't exist at the persistence layer: nothing stops an `Episode` from being *created
    and stored* with an empty thesis or null architecture in the first place. See `docs/SCHEMA.md`.
14. **`generation_fingerprint` is never computed.** The column and `UniqueConstraint(subject_id,
    generation_fingerprint)` are real; nothing anywhere computes a fingerprint. The constraint has
    never fired.
15. **`gate.py` was narrower than `CLAUDE.md`'s own R1.** — *fixed today, see §9.*

### Architecture space

16. **`misconception` and `open_question` are unbuildable.** Both need DISPUTED/CONTESTED claims.
    `claim_extraction.py`'s schema permits only `{FACT, CONTEMPORANEOUS_REPORT, INFERENCE}` —
    DISPUTED is excluded by construction, reserved for a reconciliation stage that doesn't exist.
    Confirmed empirically: zero DISPUTED and zero CONTESTED across a real 79-claim table.
17. **`investigation_led` is not distinguishable from `chronological` at generation time.**
    `EpisodeClaim` stores only `episode_id`, `claim_id`, `position` — an untagged integer. Nothing
    records which axis an ordering represents. `claim_type` is epistemic, not temporal;
    `date_anchor` is when the event happened, not when it was discovered. Two episodes on the same
    claim pool can carry byte-identical `EpisodeClaim` rows under different architecture labels and
    nothing notices. **This is the Bucket 1 failure, present, not a risk.**
18. **`context_first` has no material — a source-content gap, not a schema gap.** All 14
    LOCATION/TIMELINE claims in a real table are case-event claims wearing a setting label. The two
    LOCATION claims are one fact stated twice. Untested hypothesis: a source chosen for period or
    social history content might produce genuine setting claims. No such source has ever been
    fetched.

> ### **The effective architecture space is 2, not 6: `chronological` and `record_forward`.**
> The uniqueness guarantee is thesis × architecture × claim subset. That middle dimension is
> currently one third of its documented size.

19. **Architecture availability is per-subject, not global.** It depends on what sources exist for
    a case. A subject with no Tier A source has an architecture dimension of zero regardless of what
    the enum names. This was not previously written down anywhere.
20. `record_forward` needs a minimum-claims-per-source threshold. That is a **selection-time check,
    not a schema gap** — the count query already works, only the number is undecided. Contrast with
    #17, where the data doesn't exist to check in the first place.

### Sourcing

21. **`narratable` is never set automatically.** `claim_extraction.py` hardcodes `narratable=False`
    on every claim. Flipping it requires a deliberate `Claim.before_update` write — an editorial
    act. Only 2 narratable claims exist in the entire database, both seed data.
22. **Heuristics never auto-assign Tier A.** A genuine CourtListener court-opinion PDF sits at
    UNVERIFIED because nobody manually promoted it. Rationale: a .gov domain can host a blog post
    about a case as easily as the filing itself.
23. **Tier A primary sources for old cases often aren't on the open web, and I will not build
    bot-wall evasion.** Confirmed blocked: famous-trials.com and lizzieandrewborden.com (Cloudflare
    JS challenge), loc.gov / Chronicling America (403 on article, OCR endpoint, and robots.txt),
    HathiTrust (403), ArchiveGrid (403 — this one hides the holding institution for Frank H. Burt's
    actual stenographic Borden transcript, the single best lead found).
24. Archival photos are often ~1000px, below the 1920px floor for zoom. Static shots are cheap but
    a slideshow is YouTube's bucket 1.
25. Claim extraction reaches procedural content reliably, contested content unreliably.
26. Vertical formats need separate renders, not crops.
27. **Claim extraction has no dedup and no idempotency.** `subject_id=8` holds 45 claims from one
    source (stacked `--force` reruns) representing roughly 8 distinct facts. Beyond the review
    cost: an inflated claim pool inflates the claim-subset dimension of the uniqueness guarantee
    without adding real variation.
28. **`POST /subjects/{id}/sources` accepts caller-supplied `tier`, `text_sha256`, and `word_count`
    with no fetch, no robots.txt check, no Tier C check, no dedup, no boilerplate check.** A caller
    can assert `PRIMARY_RECORD` on content nobody retrieved and satisfy R1 condition 2 for a source
    nobody read. Currently only exercised by tests.

### Script generation

29. **Closed.** Step 2 (the six-section structure) is what closed it: `generate_script` now
    builds real Ground/Sequence/Resolution allocation, cold-open selection, and rule 6/7
    preconditions — genuinely architecture-specific behavior, not a flat concatenation
    indifferent to what `Episode.architecture` said. One residual gap, not the same finding:
    nothing checks that `Episode.architecture` actually **equals** `CHRONOLOGICAL` before running
    this logic — an episode tagged `INVESTIGATION_LED` would still get the chronological
    six-section treatment, since the render gate only checks non-null. Dispatch-by-value belongs
    one layer up (whatever calls this module for a given episode), not inside it.
30. **Closed.** `gemini_composition_provider.py` has now run against the real Gemini API
    three times (one 5-claim fixture, two 40-claim fixtures), not just the local fake
    provider. Rule 1 (never introduce a fact absent from the claim set) and the
    `claim_type`/`confidence` attribution discipline both held up across all three runs —
    contemporaneous/reported claims consistently got attribution language, contested
    claims consistently got hedged without picking a side. What did *not* hold up, and is
    the reason this closes with corrections attached rather than cleanly: the prompt's
    original word_target guidance produced repetition, not elaboration, on the first
    scale run (a thesis-bearing claim restated 2-3 times in different words) — fixed by
    forbidding restatement explicitly and giving each claim its own numeric word_target
    instead of a bare section-level total. See `docs/ARCHITECTURES.md` §2/§3.4 and this
    document's own §11 for what closing this finding actually changed: the 20-minute
    target is withdrawn, and `thesis_bearing` turned out to govern claim inclusion, not
    composed word count.
31. **Chronological ordering and claim absorption are structurally in tension.** The
    anti-repetition fix's intended alternative to restating a claim was absorption —
    a large-word_target claim "drawing in" neighboring claims, subordinating them into
    one developed passage instead of each getting its own separate sentence. Measured
    directly: it worked in Ground (5 claims) — the model merged two pairs of claims into
    shared sentences via clauses like "...where Alden Reyes had worked..." It did not
    happen at all in Sequence (30 claims, real content) — every claim landed as its own
    plain sentence regardless of word_target, thesis-bearing or not (the 1.07× finding,
    #30 above). Sequence's own rule 5 (`docs/ARCHITECTURES.md` §4) requires strict
    `date_anchor` order with no exceptions — genuine absorption usually means writing
    about a later or earlier claim's detail inside an earlier or later claim's sentence,
    which reorders which claim's *content* appears where even if claim *order* is
    preserved in a technical sense. Untested whether this is a claim-count effect (5 vs
    30), an ordering-constraint effect, or both — only one data point exists for each
    condition. Worth a run that varies claim count under the ordering constraint before
    concluding which one is the real cause.

### Sourcing gate, measured

32. **R1's gate is measured, not estimated, and strategy 1's only sourced subject fails
    it.** `check_source_gate()` (`packages/research/gate.py`) requires, live DB values for
    `strategy_id=1` (`criminal-cases`): `min_verified_sources=3`, `min_primary_records=1`,
    `min_distinct_domains=3`. Subject 8 scores **1/1/1** — one verified source, one Tier A
    source, one domain — and fails conditions 1 and 3 (`INSUFFICIENT_VERIFIED_SOURCES`,
    `INSUFFICIENT_DISTINCT_DOMAINS`); only condition 2 passes. **Claim count plays no role
    in the gate at all** — it counts `Source` rows exclusively, so a subject with 45 claims
    from that one source scores no better than a subject with one claim from it. A clean
    extraction of Borden into its own subject would score identically: sources 5 and 6 (the
    contaminating Antonio Long and Hinterkaifeck sources sharing subject 8) are `UNVERIFIED`
    tier and never count toward any of the three conditions, in either subject.
    **Consequence: strategy 1 currently has no subject that can produce an episode.**
    Thirteen archives were checked looking for a second independent Borden domain
    (`docs/SCHEMA.md`'s Cloudflare/403 findings plus the eight-archive batch in §10) and all
    thirteen were blocked; only `crimearchives.net` ever worked. **This is a sourcing
    failure, not a claim-quality or tooling failure** — the 45 Borden claims are eligible to
    be narratable right now (single Tier A source each, the sourcing guard would pass) and
    the flag was simply never set on any of them, which is a separate, trivially-fixable
    editorial gap, not what's actually blocking an episode. Strategies 2 and 3 (§11's own
    note that strategy 1 was built first specifically because it's the hardest of the three)
    have current, multi-domain, robots-friendly sources and are expected to clear these same
    thresholds routinely — given this measured result, that is now **the reason to build
    them next, not a stated preference**.

### Strategy 3 (film-tv-news), and a sharper claim-duplication number

33. **`Subject.resolution_status` has no meaningful value for film-tv-news; the decision is to
    use `OFFICIALLY_RULED` as an inert placeholder rather than migrate the enum.**
    `resolution_status: ResolutionStatus` is a required, non-nullable column shared by every
    strategy (`packages/db/models.py`), and all five `ResolutionStatus` values (`CONVICTED`,
    `ACQUITTED`, `UNSOLVED`, `OFFICIALLY_RULED`, `DISPUTED`) are criminal-justice vocabulary
    with no reading for a weekly entertainment-industry topic. `film-tv-news`'s own scorer
    (`packages/strategies/film_tv_news/eligibility.py`) reads nothing from this field, by
    design, rather than picking a value and pretending it means something — but every real
    film-tv-news `Subject` still has to write *something* into the column. `OFFICIALLY_RULED`
    is the placeholder because it reads closest to "not in dispute, nothing to resolve," and it
    is inert by construction here since nothing checks it for this strategy. The real fix would
    be migrating `ResolutionStatus` into a strategy-owned enum the way `RiskFlag` and the
    category enums already are; that is a schema change and out of scope for this decision.
34. **`subject_id=8` measures 79 claim rows but only 38 distinct claims at 0.75 similarity —
    roughly 52% duplication, measured, not eyeballed** (`scripts/measure_claim_duplication.py`).
    The same restatement pattern appears across all three cases sharing that subject row
    (Borden, Antonio Long, and Hinterkaifeck alike), so this is extraction behavior, not a
    fixture artifact specific to one case. `MIN_TOTAL_CLAIM_COUNT` and the word budget it drives
    (`packages/script/chronological.py`) both count rows, not distinct facts, and are inflated
    accordingly: `WORDS_PER_CLAIM = 18` was itself measured on composed output where duplicates
    had already been folded together by the model, so `total_words = claim_count *
    WORDS_PER_CLAIM` overestimates by roughly 2x against raw claim counts. Sharpens finding
    #27's earlier, cruder estimate ("roughly 8 distinct facts" from 45 rows) into a validated
    number.
35. **Trade-source reachability for film-tv-news is measured, and it clears easily.**
    `variety.com`, `hollywoodreporter.com`, `deadline.com`, `thewrap.com`, and `indiewire.com`
    all allow fetching under `robots.txt` and extract 2000-4100 characters of real body text
    from one real, current article apiece. `boxofficemojo.com` is robots-disallowed via an
    allowlist naming only named crawlers (Googlebot, bingbot, and similar), citing IMDb's
    anti-scraping terms directly in the file. 5/6 domains reachable, against 1/13 archives
    tried for strategy 1's own hardest case (finding #23) — direct, measured evidence for §11's
    stated expectation that strategies 2 and 3 have sources strategy 1 does not.

### Strategy 3: the gate passes, measured, and why

36. **R1's source-diversity gate passes for film-tv-news, measured against a real subject.**
    Subject 10, five real trade articles: `verified_source_count=5`, `tier_a_source_count=5`,
    `distinct_domain_count=5`, against that strategy's own `3/1/3` threshold. Direct comparison
    to finding #32: strategy 1's only sourced subject scored `1/1/1` against the same shape of
    gate and failed two of three conditions. The gate that blocks strategy 1 is cleared for
    strategy 3 — not a projection, a measured run.
37. **Claim duplication for film-tv-news is 0.0%, measured the same way finding #34 measured
    ~52% for `subject_id=8`.** Single-linkage clustering at 0.75 similarity
    (`scripts/measure_claim_duplication.py`) on the aggregate film-tv-news subject: 32 raw
    claims, 32 distinct. The mechanism is structural, not incidental: `subject_id=8` accumulates
    the same handful of facts (a verdict, a deliberation time) restated by many near-identical
    sentences about one event, while a film-tv-news subject aggregates several unrelated
    stories in one week, and no two source articles restate the same fact across different
    stories. Aggregating by week rather than by event is what eliminates the restatement
    problem, not a difference in extraction quality.
38. **Claim yield per article splits sharply by article type, measured in claims per 1000
    extracted characters** (`scripts/measure_film_tv_yield.py`'s own figure, added for exactly
    this reason): `hollywoodreporter.com` 2.96, `deadline.com` 3.45 — both conventional
    reporting — against `variety.com` 0.60 (a streaming listicle) and `indiewire.com` 0.55 (a
    festival-lineup announcement). Sourcing for this strategy should target reporting and skip
    roundups/listicles; a listicle's high character count is not high claim density. Four
    articles yielded 32 distinct claims — `32 * WORDS_PER_CLAIM (18) = 576` words, `576 / 150
    wpm * 60 = 3:50` — a real per-run runtime figure from real yield, not an assumption.
39. **`assign_initial_tier` is strategy-aware; `strategy_slug` is now a required parameter.**
    "Heuristics may never write Tier A" was criminal-cases' own rule, not a global one:
    contemporaneity for a criminal case requires comparing an event date to a publication
    date, real human judgment a domain alone cannot make. It doesn't hold for film-tv-news,
    where a Subject spans one week and every source is published within days of the event it
    reports — contemporaneity there is structural, not a case-by-case call. criminal-cases'
    own behavior is unchanged and proven so by test (`tests/test_tiering.py`, plus every
    existing `packages/research/fetch.py` test staying green unedited). Per-strategy tiering
    rules now live in `packages/strategies/<slug>/tiering.py`, registered into
    `packages/research/tiering.py` via `register_tier_assigner` as an import side effect,
    mirroring how eligibility scoring is already strategy-owned. A strategy that registers
    nothing fails safe to `UNVERIFIED` — this is what keeps the change from silently applying
    to a future strategy nobody has reviewed.

### Gemini free-tier reliability, measured

40. **Gemini free-tier `503 UNAVAILABLE` is a sustained condition, not a transient spike.**
    Five separate occurrences across several hours of real use, each surviving
    `gemini_provider.py`'s own internal tenacity retries before finally raising. Five
    independent failures spread over hours, each one having already retried and still failed,
    is deprioritization under load, not a momentary blip a single retry would paper over —
    this is a real throughput constraint on the pipeline, not a bug to fix by retrying harder.
    `scripts/measure_film_tv_yield.py` now catches `google.genai.errors.APIError` per article
    and prints partial results instead of aborting the whole run on the first 503 — a fix
    forced by four runs that produced nothing.

### Narration timing, measured

41. **Word-count-based narration duration is a planning aid only; rendering must use measured
    audio, not an estimate.** `say -r 150` measured 11.72s for a 30-word card against a
    12.0s word-count prediction; Kokoro's `af_heart` measured 11.58s for the same 30 words —
    both real voices land close to the word-count model in isolation. Across a real 23-card
    Borden episode, though, the aggregate word-count estimate overshot the actual measured
    audio by 17.7%, with individual card error ranging from -2.3s to +1.5s in both directions —
    small per-card errors compound unevenly across a real episode's mix of card lengths in a
    way a single 30-word sample can't surface. `packages/visual/render.py` and every render
    script already only ever accept measured `ffprobe` durations, never word-count estimates,
    for exactly this reason — this finding is the number behind that decision, recorded once
    rather than re-derived per script.

### Claim/section schema facts, and subject 10's first real tagging pass

42. **Four schema facts this document was wrong about or silent on — corrected here so a
    fresh session doesn't inherit the same wrong mental model.** `Claim` has no `source_id`
    column; a claim's source is `ClaimSource` (a join table — `docs/SCHEMA.md`'s "exactly
    one `ClaimSource` per claim" finding means it's a 1:1 in practice today, but the join is
    real, not a denormalized FK). `Claim`'s text field is `statement`, not `text`. `Section`
    (`packages/domain/enums.py`) is a **two-member** enum, `GROUND`/`RESOLUTION` only —
    `NULL` means Sequence by design, not "unreviewed," and there is no ordinal or positional
    section concept (no `section=1..5`, no one-section-per-source rule). Story grouping
    within a subject already exists and needs no new mechanism: it's `ClaimSource.source_id`,
    already populated by extraction. If "each story becomes one section" is encountered
    again, it describes episode/composition format, not the `Claim.section` column. All four
    surfaced from one request that assumed `source_id` lived on `Claim` and that `Section`
    had five ordinal values tied to source count — neither is true, and this document had
    nothing correct or incorrect to say about either until now.

43. **Subject 10's `claim.section` is tagged, by hand, one-off — no script, matching
    `thesis_bearing` and cold-open selection's existing editorial-act posture.** 2 `GROUND`
    (claim 91, the Paramount–Warner Bros. merger's setup fact; claim 109, the Venice Film
    Festival's dates/location), 6 `RESOLUTION` (93/95/96/98/99, the merger's completed
    regulatory clearances; 101, the still-open California lawsuit, tagged under
    `docs/ARCHITECTURES.md` §3's "unresolved threads named as unresolved" clause, not as a
    completed clearance), 24 `NULL`. Claim 92 (the EC's *expected* approval) stayed `NULL`
    deliberately — pending, not settled, so it reads as Sequence rather than Resolution.
    Only one of subject 10's four source stories (the merger, `source_id=13` via
    `ClaimSource`) has genuine Ground/Resolution shape; the other three — variety.com's eight
    unrelated one-off items, deadline.com's box-office statistics, and indiewire.com's Venice
    lineup facts past its one Ground claim — were left untagged on purpose, because there's
    nothing in them to tag, not because they weren't reviewed. Composition not yet run
    against subject 10.

44. **`Strategy.credentials_path` (added this session for YouTube upload,
    `packages/publish/youtube.py`) is single-platform by construction, not a design
    that happens to only have one value populated yet.** It's one nullable `str` column
    on `Strategy` — one credentials file per strategy, full stop. That's already a
    simplification worth naming now, before TikTok and Meta accounts exist to expose it:
    a strategy's *channels* are the things that actually hold platform credentials
    (`docs/SCHEMA.md`'s `Channel` table already models `platform` + one row per
    account), and a single strategy will have a YouTube channel, a TikTok channel, and
    an Instagram/Facebook presence, each needing its own OAuth token. The right home for
    multi-platform credentials is `Channel.credentials_path` (strategy, platform,
    credentials_path), not a second, third, fourth column bolted onto `Strategy`. Not a
    change to make now — YouTube is the only platform with working upload code, and
    `Strategy.credentials_path` is correct for exactly that single-platform case — but
    the moment a second platform's uploader gets built, `credentials_path` needs to move
    off `Strategy` and onto `Channel`, not grow a second column next to it.

45. **`credentials/film-tv-news/client_secret.json` was committed in `a4fb4ae` (swept in
    by an unrelated commit's `git add -A`), untracked in a later commit, but `a4fb4ae`
    itself was still pushed to `origin/main` as an ancestor of a subsequent push — the
    untrack didn't remove the earlier commit's blob from history, and nothing caught
    that before the push ran. The leaked client secret has since been rotated in Google
    Cloud Console; the version that reached `origin/main` is dead and unusable. History
    was deliberately not rewritten (no `filter-repo`, no force-push) — the exposure is
    accepted as already having happened rather than disrupting shared history to hide a
    secret that no longer works anyway. `credentials/` is gitignored going forward, so
    this shouldn't recur for this or any other strategy's client secret or token file.

---

## 8. Entity extraction: validated

This was the open item for two sessions running. It is now closed.

**Subject 8 is a contaminated fixture** holding sources from three unrelated real cases (a modern
court PDF, Hinterkaifeck, Lizzie Borden), 25 entities with zero overlap. Retitled in place, rows
preserved because 79 claims of documented investigation history depend on them. It can never host a
matching test.

**Subject 9** (`1922-hinterkaifeck-farmstead-murders`) was built clean. Four English candidates
fetched and hand-checked *before* spending any quota — the check that source_7 skipped. Wikipedia
was rejected: it names a **third** Cäzilia (b. 1881, from a first marriage) and calls Josef
"Josef Gruber" in an incest-paternity paragraph. Note: **no source anywhere writes "Josef Gabriel"
as a literal string.**

Three real runs, three Gemini calls:

| Run | Result |
|---|---|
| Founding (mentalfloss) | 10 entities. Two Cäzilias created distinct. |
| source_11 (tagged "(senior)"/"(junior)") | 8/10 matched, 0 new, 0 rejections. junior→29, senior→32. |
| source_10 (**no tags**, age + relationship only) | 8/10 matched, both Cäzilias distinct. |

In both matching runs: **no rationale argued from surname presence or absence**, including on the
pair where the surname was available to lean on. That was the failure mode that would have
invalidated a correct merge.

One nuance worth keeping: source_11 was chosen for its explicit "(senior)" tag, but the model didn't
cite that span — it matched via "his wife Cäzilia" and reasoned from relationship. So the tag only
helped one of the two entities it was meant to help.

**Match-or-new works at n=10, tagged and untagged.** Still untested: n≈200, name-variant spellings,
and the rejection path.

---

## 9. The blocker, and the fix

Every subject in the project failed R1's source gate. `strategy_id=1` requires
`min_verified_sources=3`, `min_primary_records=1`, `min_distinct_domains=3`.

The `min_primary_records` condition counted `tier == PRIMARY_RECORD` **only**, excluding
CONTEMPORANEOUS. That made every historical case unbuildable, because pre-digitization primary
records are behind bot walls or not digitized at all.

It turned out to be **drift, not a decision**:

- `CLAUDE.md`'s own R1 names *"contemporaneous news archive"* directly as an example of a
  primary/public record.
- `SOURCING.md` lists primary-record and contemporaneous sourcing as undifferentiated bullets under
  one Tier A heading.
- `TIER_A_SOURCE_TIERS` = `{PRIMARY_RECORD, CONTEMPORANEOUS}`, and **six** other enforcement points
  use it and treat the two identically. `gate.py` was the only divergence.
- Neither doc states a rationale for the narrower scope.
- `POLICY.md` never mentions source tier at all — its argument is entirely about structural
  variation and non-interchangeability.

**Applied:** condition 2 widened to `tier in TIER_A_SOURCE_TIERS`. `MISSING_PRIMARY_RECORD` →
`MISSING_TIER_A_SOURCE`, `primary_record_count` → `tier_a_source_count`, propagated through
`apps/api/schemas.py`, `apps/api/routers/sources.py`, `lib/domain.ts`, `GateStatus.tsx`, and
`api/schema.ts` regenerated from the running API rather than hand-edited.

A passing test asserted the old behaviour. It was **rewritten, not deleted** —
`test_gate_fails_on_missing_primary_record` → `test_gate_fails_with_no_tier_a_source`, rebuilt from
RETROSPECTIVE/BOOK/REFERENCE sources so it still tests condition 2, now correctly scoped. A new
positive test covers the widened case. 321 → 322 passing.

Gate thresholds live as `Strategy` table columns, seeded by `scripts/seed_dev.py`, with no update
endpoint by design — weakening R1 is meant to require a reviewed code change, not a toggle.

---

## 10. Next steps, in order

**The three-domain Borden plan below is dead.** Eight archives were checked — cdnc.ucr.edu,
virginiachronicle.com, nyshistoricnewspapers.org, lizzie-borden.com, digitalcommonwealth.org,
newspaperarchive.com, genealogybank.com, archive.org — and exactly one, `crimearchives.net`, turned
out usable. The rest were robots.txt disallow-all (most state newspaper-archive platforms run an
identical Veridian-based blocklist) or a Cloudflare JS challenge, same shape as finding #23.
`subject_id=8`'s single CONTEMPORANEOUS source stands as-is; finding a second and third domain is
not the next step anymore.

`docs/ARCHITECTURES.md` (v2, authoritative) is the spec the generator is built against.

**Steps 1, 2, and 3 are all done:** `EpisodeClaim.thesis_bearing`, `Claim.section`,
`Episode.cold_open_claim_id` (migrations + model fields); `generate_script(session,
episode_id, ...)` returning `SectionedScript` — the render gate, rules 6 and 7, the
narratable re-check, section allocation, all four cold-open validations; and
`compose_episode(session, episode_id, provider)` — the async entry point wiring per-section
composition calls onto that allocation, 2–4 per episode. All tested, 355 passing. See §5.

Step 3 has never run against real Gemini — everything above is tested against a local fake
provider only (§5, §7 finding #30). New next steps, in order:

1. **Run `compose_episode` against real Gemini, once.** This costs quota — 2–4 calls, for
   whichever subject actually clears R1's gate by then — and is the first real test of
   `gemini_composition_provider.py`'s prompt. Decide before spending it: which subject,
   which episode, and what "good enough" composed prose looks like, since nothing has
   checked the prompt's rule 1 (never introduce a fact absent from the claim set) or its
   `claim_type`/`confidence` discipline against a real model yet.
2. **Claim-to-image mapping (`packages/visual/`).** This, not script quality, is the real
   blocker on a watchable episode. The seam test already proved the render path works; it
   also proved the imagery has no relationship to the narration, since no claim-to-image
   mapping exists anywhere yet — see §5.

Why Borden and not Hinterkaifeck: Hinterkaifeck's Tier A material is 1922 German police and inquest
paperwork, almost certainly not on the open web. All four fetched sources are non-Tier-A. It also
scores `monetization_tier=RED` with the eligibility note *"CHILD_VICTIM present: not eligible for ad
revenue, no framing rescues this."*

---

## 11. Decisions and why

Things the repo records but doesn't explain — the reasoning behind choices that show up as
code shape, not comments.

**Thesis-bearing is hand-flagged, never model-inferred.** `EpisodeClaim.thesis_bearing` is
set at episode creation, by a person, from a fixed claim pool. The alternative — a model
reading the claim pool and inferring which claims carry the thesis — was rejected because it
converges: the same pool, scored for emphasis by the same model, tends toward the same
claims every time. That's `POLICY.md` bucket 1's failure (interchangeable output) arriving
through the data layer instead of the prose layer. Raising temperature on that inference call
wouldn't fix it either — see §2, "the same episode with different words is the same failure."
A human choosing which claims matter is a real different-episodes mechanism; a model scoring
salience against a fixed pool is not.

**`Claim.section` lives on `Claim`, not `EpisodeClaim`, and `thesis_bearing` lives on
`EpisodeClaim`, not `Claim` — this split is intentional, not incidental.** `section` answers
*where* a claim goes structurally (Ground, Sequence, Resolution), which is a property of the
claim itself, true across every episode that uses it. `thesis_bearing` answers *how much
weight* a claim gets in one specific episode's argument, which depends on that episode's
thesis, not on the claim. The two questions are orthogonal by construction: a Ground claim
can be thesis-bearing and get elaborated inside Ground (decided earlier, see
`chronological.py`). Putting `section` on `Claim` means it's set once and amortizes across
every episode that reuses the claim; putting `thesis_bearing` there instead would force it to
mean the same thing in every episode, which contradicts the entire reason thesis exists as a
per-episode field.

**20 minutes is withdrawn — the runtime target that replaced it, and why, is `docs/ARCHITECTURES.md`
§2, not repeated here.** The short version: it assumed thesis-bearing claims could be elaborated
to ~145 words each, and three real runs against real Gemini never produced that at any target
tried — a 628-word/claim target landed at ~26 actual, a 188-word target landed at 60.3 actual
(and only by restating the claim two or three times, which rule 1 forbids), and a 71-word target
landed at 16.0 actual once restatement was closed off. Word budget is now claims × `WORDS_PER_CLAIM`
(`packages/script/chronological.py`) instead of minutes × `narration_wpm`; runtime is now a report
(`SectionedScript.derived_runtime_minutes`) computed from the word count, not an input that
produces it.

**`WORDS_PER_CLAIM` is 18, not 28 — 28 was this project's own mistake, caught one session later.**
The session that introduced `WORDS_PER_CLAIM` set it to 28 and described that as "the top of the
measured range," but the range it cited in the same breath was 15.0–18.4 (non-elaborated) and
16.0–21.0 (thesis-bearing) — 28 was above both, an assertion, not a measurement. Corrected to 18,
the actual top of the non-elaborated range, which is the relevant one now that the 60/40 split
(below) no longer distinguishes thesis-bearing claims from anything. **This will need to rise, and
be re-measured rather than re-guessed, the day a prose pass adds connective tissue between
claims** — both measured runs wrote one plain sentence per claim, nothing more. `MIN_TOTAL_CLAIM_COUNT`
(40) is known to produce a ~4.5–5.0-minute episode at this rate (40 × 18 ÷ 145–160 wpm), not the
~7.5 minutes the 28-word version of this number implied; an 8-minute episode needs ~65 claims, a
10-minute episode ~80 (`1,160 ÷ 18` and `1,450 ÷ 18` at 145 wpm). The 45-claim Borden pool — the
only real Tier A claim data this project has — produces 45 × 18 = 810 words, **~5.6 minutes**, the
one figure here computed against real sourced claims rather than a synthetic fixture. None of these
are code changes; what changed is that the floor's implication is now legible, which makes it a
sourcing target, not just a gate check. See `docs/ARCHITECTURES.md` §2's own "drift risk, resolved"
note — the claim-count floor used to live in three places that could disagree with each other; now
there's one source of truth (`WORDS_PER_CLAIM`) and the rest cite it.

**`thesis_bearing` governs claim selection, not word allocation — and §3.4's 60/40 split is now
removed, not just demoted.** The three real runs that killed the 20-minute target also measured
whether the split produces the differentiation §1 originally described — a thesis-bearing claim's
composed passage noticeably longer than a non-thesis-bearing one's — and it mostly doesn't: 3.28×
in the one run that showed a real gap, and that gap was built by restating the claim, not
developing it (rule 1 violation, since fixed); 1.07× and 1.27× in the two measurements taken after
restatement was forbidden — essentially flat. That alone argued for demoting the split to "minor
nudge." Correcting `WORDS_PER_CLAIM` from 28 to 18 in the same pass argued for removing it outright:
at 18, 60/40 on a real Sequence section (6 thesis-bearing among 30, the real fixture's shape) gives
the 24 non-thesis-bearing claims ~8 words each — below the length of the claim statement itself.
The split only ever looked harmless because it was dividing an inflated total; at an honest rate
there's no room left in it that doesn't truncate someone below their own source material.
`_apply_word_targets` now gives every claim in a section the same `word_target`
(`round(section_budget / len(claims))`), no branching on `thesis_bearing` at all — the field is
still sent to the model per claim (for tone) and rule 6 still requires 5–10 thesis-bearing claims
per episode, but neither of those touches word count anymore. The uniqueness mechanism that
actually varies episode to episode is which claims get marked thesis-bearing at all — a real,
human, per-episode selection act that changes what's *in* the pool. It was never really about how
many words the prose spends on each one once it's in. See `docs/ARCHITECTURES.md` §3.4 for the
full measured table and the arithmetic showing why no split survives at the corrected rate.

**Composition is per-section, not per-claim.** One call per claim (Sequence's thesis-bearing
claims plus the rest, plus Return) runs to roughly 36 calls for a single episode — almost
double the entire 20/day free-tier quota before Ground or Resolution need anything. One call
per section is 2–5 calls per episode (§5, §10). This isn't a quality tradeoff being made for
cost reasons; per-claim composition is not affordable at all on the free tier, so per-section
is the only version of step 3 that can run.

**Strategy 1 (true crime/horror) was built first, and it's the hardest of the three.** Its
sources are disproportionately bot-walled or paywalled (finding #23), and `CHILD_VICTIM`
makes a large share of famous cases ad-ineligible outright (§10's note on why Borden, not
Hinterkaifeck, and §12's open question on how far that rule generalizes). Nothing in
`packages/` is strategy-specific — the schema, the gates, and the generator all work off
`Strategy` rows and `Subject`/`Claim`/`Episode`, not off any true-crime-only assumption.
Strategies 2 (celebrity news) and 3 (film/TV news and trivia) have current, multi-domain,
robots-friendly sources — building strategy 1 first means the hardest sourcing problem was
solved (or found unsolvable, per finding #23) before the other two ever need to prove the
pipeline is actually strategy-agnostic.

**The real blocker on a watchable episode is claim-to-image mapping, not script quality.**
Steps 1–3 (§5) are real, tested work, but the seam test (§5) is the evidence for this
decision: it proved the render path works end to end, and in the same run proved the imagery
has no relationship to the narration, because no claim-to-image mapping exists anywhere yet.
Script composition improving further doesn't move that number. `packages/visual/` is next
because it's the thing actually standing between the current state and a video anyone would
watch, not because script work is finished.

## 12. Open questions to decide, not to code

- **With the architecture dimension at 2, thesis and claim subset carry nearly all the uniqueness
  burden. Thesis is human-authored and unvalidated. That means I am the variation mechanism right
  now, not the system.** Is that acceptable for a pipeline meant to run itself?
- `CHILD_VICTIM` produces "no framing rescues this" on a flagship case. If that rule holds, a large
  share of famous true-crime cases is ad-ineligible. This is a strategy-1 question and it should be
  faced before script generation, not after.
- Writing `docs/ARCHITECTURES.md` properly is editorial work, not engineering work. Every section
  name, boundary, thesis placement and time budget in the current draft was invented because the
  docs specify none. This is the actual product — what makes a casefile episode not
  interchangeable — and it can't be delegated.
- Does `record_forward` have a claim-density threshold? The query exists; the number is a product
  decision.
- Is investigation_led worth a schema addition (a discovery-order field on `ClaimSource`), or is it
  worth dropping? The column is trivial; populating it is not — extraction has no capability to ask
  a source when investigators learned something.
- **Strategy 1 has zero subjects that clear R1 right now** (finding #32, §7) — Borden's own
  measured 1/1/1 against a 3/1/3 gate, after thirteen archives failed to produce a second
  domain. Keep spending sourcing effort on strategy 1, or build strategy 2 or 3 next, where
  the same gate is expected to clear routinely? This is a scheduling decision this document
  can surface but not make.

---

## 13. Read these first

- `docs/SCHEMA.md` — every design decision, investigation, rejected alternative and why. Longest
  and most important.
- `docs/SOURCING.md` — stage 1 spec, claim table, source tiers, the variation manifest
- `docs/POLICY.md` — monetization constraints, 12 derived requirements
- `docs/ARCHITECTURES.md` — v2, authoritative. The generator is built against this, superseding
  `docs/SCHEMA.md`'s older architecture-space findings' framing of it as an unreviewed DRAFT.
- `experiments/slice_01/FINDINGS.md` — render timings, resolution finding
- `CLAUDE.md` — working conventions
