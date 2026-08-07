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

- **Propose before you code.** Don't apply changes until I confirm — this includes changes you
  think are prerequisites.
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
- Tests: **322 passing**, mypy strict clean, ruff clean

**Gemini free tier is 20 requests/day/project.** Two calls per source (claims + entities), so ten
sources a day, shared with every dry-run and prompt experiment. This is a real constraint on every
session — never retry a failed run without deciding to spend the quota.

---

## 5. What is built

**Media pipeline**, validated end to end in `experiments/slice_01`: 8.1 min render for a 20-minute
episode static, 14.0 min with Ken Burns.

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

**Roughly 28% of the full vision.**

---

## 6. What is not built

- **Script generation** — `packages/script/` does not exist. This is the next piece, the missing
  link between the finished data layer and the working media pipeline.
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

13. **The thesis render gate does not exist.** `SCHEMA.md` says thesis and architecture are
    "enforced non-empty/non-null at a render gate check"; `POLICY.md` R1 says "Render fails without
    one." No such check exists in code.
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

1. **Build a clean Lizzie Borden subject.** Three CONTEMPORANEOUS sources across three distinct
   domains — the gate accepts that now. `crimearchives.net` already works, so two more are needed.
   1893 trial coverage is abundant, digitized, and public domain. Fetching is free.
2. **Claim extraction** on those sources (~3 Gemini calls).
3. **Flip `narratable`** on the good claims. This is an editorial act and nothing in the project has
   ever done it outside seed data. Do it carefully the first time.
4. **Script generation**, against `chronological` and `record_forward` only — that is what the data
   actually supports. `docs/ARCHITECTURES.md` exists as a DRAFT spec for four architectures and is
   expected to be rewritten by hand.

Why Borden and not Hinterkaifeck: Hinterkaifeck's Tier A material is 1922 German police and inquest
paperwork, almost certainly not on the open web. All four fetched sources are non-Tier-A. It also
scores `monetization_tier=RED` with the eligibility note *"CHILD_VICTIM present: not eligible for ad
revenue, no framing rescues this."*

---

## 11. Open questions to decide, not to code

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

---

## 12. Read these first

- `docs/SCHEMA.md` — every design decision, investigation, rejected alternative and why. Longest
  and most important.
- `docs/SOURCING.md` — stage 1 spec, claim table, source tiers, the variation manifest
- `docs/POLICY.md` — monetization constraints, 12 derived requirements
- `docs/ARCHITECTURES.md` — DRAFT, unreviewed, expected to be rewritten
- `experiments/slice_01/FINDINGS.md` — render timings, resolution finding
- `CLAUDE.md` — working conventions
