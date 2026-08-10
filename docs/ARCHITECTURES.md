# ARCHITECTURES.md

**Status: v4.** Specifies `chronological` only. `record_forward` is unwritten.
`investigation_led`, `context_first`, `misconception` and `open_question` are not
buildable against the current data layer — see `docs/SCHEMA.md` findings #16–#18.

Changes from v3 (this revision): `WORDS_PER_CLAIM` corrected from 28 to 18 — 28
was asserted, not measured, against the real per-claim data v3 itself cited;
18 is the top of the actually-measured non-elaborated range (15.0–18.4 words
across two real runs). §3.4's 60/40 split is **removed**, not demoted further
— at the corrected, lower per-claim rate, 60/40 would give Sequence's
non-thesis-bearing claims ~8 words each, below the length of the claim
statement itself, so there was no honest split left to demote. `word_target`
is now uniform per claim within a section. Every number in §2 that depends on
the rate (runtime for 40 claims, claim counts for 8/10-minute episodes, the
Borden pool's implied runtime) is recomputed against 18, not 28. See §2 and
§3.4.

Changes from v2: word budget derives from claim count (`WORDS_PER_CLAIM`), not
a target runtime — three real Gemini runs showed the runtime-derived budget
assumed an elaboration rate that was never achievable; `MIN_TOTAL_CLAIM_COUNT`
is reframed as a sourcing target with a known runtime rather than an undecided
placeholder.

Changes from v1: word budget derives from `VariationProfile.narration_wpm` rather
than a hardcoded rate; cold open composes with `ColdOpenStyle`'s four variants
rather than superseding them; rules are split into generation-time and audit.

---

## 1. What `chronological` is

Events in the order they happened, with the thesis stated early and earned by the
end.

What makes an episode non-interchangeable is **not** the ordering. Date order is
the same for everyone. It is that the thesis decides **what claims are even in
the pool** — which claims a human marked thesis-bearing, which is what actually
varies episode to episode. It is **not**, as this section originally claimed,
that composed word count differs claim to claim within a section: §3.4 records
three real runs against real Gemini that measured this directly, and it doesn't
happen — a thesis-bearing claim's composed passage is not reliably longer than a
non-thesis-bearing one's. "One spends four minutes on the dress and thirty
seconds on the verdict" was the intended mechanism, not an observed one.

That mechanism — thesis-bearing status changing which claims are selected into
an episode's pool at all — is §4. Without it, thesis is decorative and this
architecture produces one episode per claim pool.

---

## 2. Time and word budget

**Withdrawn: the 20-minute target.** It was derived from an elaboration rate —
8 thesis-bearing claims composed to ~145 words each (§3.4, as originally
written) — and three real runs against real Gemini
(`gemini_composition_provider.py`, `docs/HANDOFF.md` §11) never produced
anything close to that, at any word_target tried: 628 words/claim (a 5-claim
fixture, every claim thesis-bearing) landed at ~26 actual; 188 words/claim (a
40-claim fixture) landed at 60.3 actual, and only by restating the claim two or
three times over in different words, which is exactly what rule 1 (never
introduce a fact absent from the claims) forbids; once restatement was
explicitly forbidden in the prompt, a 71-word target for the same shape of
claim landed at 16.0 actual. **A target derived from an elaboration rate that
was never achievable was never going to produce a 20-minute episode, or any
particular runtime — it produced whatever composing each claim once, plainly,
actually took.** See §3.4 for what those three runs mean for the thesis
mechanism itself, not just the runtime number.

**Word count is now derived from claim count, not target runtime:**

```
WORDS_PER_CLAIM = 18
total_words = len(episode_claims) * WORDS_PER_CLAIM
```

**28 was this project's own mistake, corrected here, not a starting point.**
The previous revision of this document set `WORDS_PER_CLAIM` to 28 and
described it as calibrated to "the upper end" of measured claim length — but
the actual measured range it cited alongside that number was 15.0–18.4 words
(composed, non-elaborated claims, two real runs) and 16.0–21.0 (thesis-bearing,
same runs) — 28 was above *both* ranges, not the top of either. It was an
assertion dressed as a measurement. **18 is the top of the non-elaborated
range, not above it** — 15.0–18.4 measured, 18 chosen. The non-elaborated
range is the relevant one now that §3.4's split is removed and every claim
gets the same treatment (see below), not just the "rest" group.

**This number will rise, and should be re-measured, not re-guessed, when it
does.** Both real runs this range is drawn from wrote each claim as its own
plain sentence — no connective tissue between claims, no transitions, because
nothing in the prompt asked for any. A later prose pass that adds transitions
or genuinely combines adjacent claims into one sentence will use more words
per claim than 18. When that pass exists, measure its actual output the same
way this number was measured (real Gemini runs, real word counts, not a guess
at what a plausible connective-tissue rate might be) rather than bump this
constant on reasoning alone.

Section budgets are still percentages of whatever the total comes to — the
percentages themselves are unchanged, only what "the total" is derived from:

| # | Section | Share |
|---|---|---|
| 1 | Cold open | 4% |
| 2 | Thesis | 2.5% |
| 3 | Ground | 10% |
| 4 | Sequence | 65% |
| 5 | Resolution | 14% |
| 6 | Return | 4.5% |

Sequence at 65% is a deliberate claim: this architecture is mostly the events.

**Runtime is now a report, not an input.** `SectionedScript.derived_runtime_minutes`
is `total_words / VariationProfile.narration_wpm`, computed after the word
count, not the other way around — rule 4 reports the length an episode will
actually run, instead of checking words against a target nothing was ever
going to hit. `episode_target_minutes` survives as an injectable parameter on
`generate_script`/`compose_episode` (same shape as `min_claim_count`) but no
longer feeds the budget; nothing enforces the runtime it used to imply.

**`MIN_TOTAL_CLAIM_COUNT` (40, unchanged this session) is no longer a
placeholder — it's a known, and shorter-than-previously-thought, runtime.**
40 claims × 18 words = 720 words. At `narration_wpm` 145–160 (the range this
project has used), that's 720 ÷ 160 = 4.5 to 720 ÷ 145 = 5.0 minutes — **call
it ~4.5–5.0, not the ~7.5 minutes the previous (28-word) revision of this
document computed, and nowhere near the 20 minutes originally envisioned.**
Reaching longer runtimes at 145 wpm needs, by the same arithmetic
(`runtime_minutes * narration_wpm / WORDS_PER_CLAIM`):

| Target runtime | Claims needed (145 wpm) |
|---|---|
| ~4.5–5.0 min | 40 (`MIN_TOTAL_CLAIM_COUNT`, unchanged) |
| 8 min | 1,160 ÷ 18 = 64.4 → **~65** |
| 10 min | 1,450 ÷ 18 = 80.6 → **~80** |

**The existing 45-claim Borden pool (`docs/SCHEMA.md`, the only real Tier A
claim data this project has) produces 45 × 18 = 810 words, ~5.6 minutes at 145
wpm** — the one number in this section computed against real sourced claims
rather than a synthetic fixture, and it lands close to the 40-claim floor's
own ~5-minute implication, not near 8 or 10 minutes.

None of this is a code change — `MIN_TOTAL_CLAIM_COUNT` is still 40 — what
changed is that this number is now legible as a **sourcing target**, not an
abstract gate check: a subject that clears R1 with 40 claims produces a
~5-minute episode; a subject that needs an 8-minute episode needs sourcing to
reach ~65 narratable claims, a 10-minute episode ~80, not just clear R1's
independent-sources-and-tier thresholds. Whether 40, ~65, ~80, or some other
number is the right floor to actually gate on is a product decision this
paragraph doesn't make — it only makes the implication of whichever number is
chosen visible.

**Drift risk, resolved, not just noted.** The claim-count floor used to live in
three places that could silently disagree — this section, rule 7 (§4), and
`MIN_TOTAL_CLAIM_COUNT` in code — with nothing tying them together, and this
section used to carry two competing, unresolved readings of what the right
number even was. Both are gone: `WORDS_PER_CLAIM` in
`packages/script/chronological.py` is the one place the words-per-claim rate
lives, this section and rule 7 describe what it implies rather than
maintaining a second copy of a number, and there is exactly one reading of the
budget math now, not two.

---

## 3. Sections

### 1. Cold open
One claim, pulled out of chronological order. Its **form** is
`VariationProfile.cold_open_style`:

- `SCENE_FIRST` — the most concrete physical claim. An object, a time, a distance,
  a wound, a sum of money.
- `QUESTION_FIRST` — the claim that the episode's thesis answers, posed as the
  open question it was at the time.
- `RECORD_QUOTE` — a claim whose `quoted_span` carries period language worth
  hearing verbatim.
- `TIMELINE_ANCHOR` — a date and what happened on it, stated flat.

Applies to all four:
- Exactly one claim.
- Must be one of the thesis-bearing claims. The cold open is chosen from
  claims the human already flagged; `cold_open_style` selects among those. A
  heuristic picking from the whole pool would give the same answer every
  time, which is the failure §4 exists to prevent.
- It must also appear in Sequence at its correct chronological position.
- Never the verdict, never the outcome.
- No names explained, no orientation.

**Selection:** `Episode.cold_open_claim_id`, a nullable FK — one claim, one episode,
enforced structurally by the column itself, not by convention. The FK is declarative
only: `packages/db/session.py` never enables SQLite foreign-key enforcement (confirmed
empirically against a scratch database, not assumed), so `generate_script` has to
validate at generation time that the referenced claim exists, belongs to this episode's
claim set, and is thesis-bearing — none of the three are guaranteed by the column alone.

### 2. Thesis
`Episode.thesis`, stated plainly in the narrator's voice as a declarative
sentence. Not a question, not a tease. If it cannot be said in two sentences it is
not a thesis.

### 3. Ground
Who, where, when — the minimum needed to follow §4.

- No claim used here that Sequence will also use.
- If the claim table has no genuine setting material, this shrinks to 30 seconds
  of names and the time goes to Sequence.

**Tagged via `Claim.section = GROUND`** — a deliberate, one-time editorial act, not
inferred. Claim-intrinsic, not episode-scoped: unlike `thesis_bearing`, tagging a claim
once holds across every future episode drawn from it, the same way `narratable` does.
`section` is nullable and null means Sequence, not unreviewed-and-blocked — the reviewer
tags Ground and Resolution and leaves everything else alone.

### 4. Sequence — **the thesis mechanism**

Events in `date_anchor` order, in 3–5 movements. A movement breaks at the largest
date gaps in the set, not at a fixed count. Each movement opens on its first claim
with no transition sentence.

**Claims are marked thesis-bearing by hand.** When you select claims for an
episode you flag the ones the thesis turns on. This is an editorial act — a
deliberate human write, inspectable afterward, never inferred by a model. A model
inferring them would reproduce the same emphasis from the same pool every time,
which is the variation failure `POLICY.md` bucket 1 describes.

Schema: `EpisodeClaim.thesis_bearing: bool`, default `False`.

**Per episode: 5–10 thesis-bearing claims.** Below 5 the thesis isn't doing enough
work to distinguish the episode. Above 10 everything is emphasised, which is the
same as nothing being emphasised.

**Word allocation inside Sequence is uniform — the 60/40 split is removed, not
demoted.** As originally written, this section specified:

- Thesis-bearing claims: ~~60%, divided among them.~~
- All other claims: ~~40%, divided among them.~~

`_apply_word_targets` (`packages/script/chronological.py`) now gives every
claim in a section the same `word_target`: `round(section_budget /
len(claims))`, no branching on `thesis_bearing` at all. Three real runs
against real Gemini are why this was removed, not just demoted:

| Run | Thesis-bearing target | Actual (avg) | Ratio vs. rest |
|---|---|---|---|
| 40-claim, 60/40, no repetition guard | 188 words | 60.3 words | **3.28×** — but by restating the claim 2-3 times in different words, which rule 1 forbids |
| 40-claim, 45/55, repetition forbidden | 71 words | 16.0 words | **1.07×** — essentially flat |
| Same run, Resolution section | 91 words | 21.0 words | **1.27×** — essentially flat |

The only run that showed real differentiation did it through restating a
claim, not developing it — the thing rule 1 exists to prevent. Once that was
closed off, differentiation collapsed to near-1×. That alone was reason to
stop calling the split a mechanism. What made it worth *removing* rather than
leaving in place as an ineffective-but-harmless nudge: `WORDS_PER_CLAIM` was
also corrected downward in the same pass, from an asserted 28 to a measured
18 (§2). At 18, a 60/40 split on a real Sequence section (e.g. 6
thesis-bearing claims among 30, the real 40-claim fixture's shape) gives the
24 non-thesis-bearing claims ~8 words each — below the length of the claim
statement itself (the shortest claim in that fixture is 7 words; most run
15–27). A split that used to look merely ineffective at an inflated total
becomes actively harmful at an honest one: it would truncate most of a
section's claims below their own source material. There is no smaller,
gentler split left to keep — uniform allocation is what's left once the
inflated total that made 60/40 look harmless is gone.

**`thesis_bearing` governs claim selection, not word allocation, full stop.**
Whether a claim is thesis-bearing still decides whether it's one of the 5–10
claims that get an episode built around them at all (§4 rule 6) — that
inclusion decision is what varies episode to episode and is what actually
produces the "one episode per claim pool" failure §1 describes if it's
missing. `thesis_bearing` is still sent to the model in the claims block
(`gemini_composition_provider.py`) for tone — a thesis-bearing claim may still
read with more weight in how it's phrased — but it has no effect on
`word_target` anymore. `word_target` itself is kept, not deleted: every claim
still gets one, uniform within its section, and it still grounds sentence
length against something rather than nothing.

The generator receives the thesis text and the flags. It does not decide which
claims matter; it decides only how to write the ones it was told matter — and
"how to write" no longer varies by how much a claim matters, only "which
claims matter" does.

### 5. Resolution
What the record settles, and what it doesn't. Verdict, outcome, aftermath.
Unresolved threads named as unresolved, once each, without speculation.

Tagged via `Claim.section = RESOLUTION` — same mechanism as Ground, §3.3.

### 6. Return
Back to the thesis, paraphrased rather than restated verbatim.

- No new claims. Every fact appeared earlier.
- No moral. No address to the viewer.

---

## 4. Rules

### Generation-time — the generator enforces these in memory
It is building the sections, so it knows what is in each. No schema support
needed. A script failing any of these does not render.

1. All prose derives from claims in the episode's `EpisodeClaim` set.
2. The cold-open claim appears exactly twice: §1 and §4. Every other claim appears
   at most twice.
3. §6 introduces no claim id not already used.
4. Section word counts within ±15% of budget.
5. §4's claims are in `date_anchor` order with no exceptions.
6. Thesis-bearing count is between 5 and 10 inclusive.
7. Total claim count ≥ 40.

### Render gate — checkable against the schema today
8. `Episode.thesis` non-empty and `Episode.architecture` non-null.
   **This is the gate `docs/SCHEMA.md` finding #13 says does not exist.** Nothing
   blocks implementing it now.

### Audit — not persistable today
Rules 1–5 can be enforced at generation time but not verified afterward, because
no section concept exists in the schema: `Script.body` is one string, and
`ScriptCitation`'s `UniqueConstraint(script_id, claim_id)` cannot record a claim
appearing twice. Recording sections would follow `Shot.script_span_start/end`'s
existing pattern. Deferred — build the generator first, decide whether audit is
needed after reading real output.

---

## 5. Manual surface

`SOURCING.md` currently states the per-episode manual work as: pick the case,
write the thesis, clear the guard checklist — five minutes. This architecture adds
three more acts, in two different buckets:

- **Per-subject, once:** tag Ground and Resolution claims via `Claim.section`.
  ~1 minute per 10 claims. Claim-intrinsic, amortizes across every future episode
  drawn from the same claim pool, the same way `narratable` does.
- **Per-episode:** flag 5–10 thesis-bearing claims (3–5 minutes), then pick the
  cold open from among them (under a minute). Neither amortizes — a second episode
  from the same subject under a different thesis needs both again, same reasoning
  as before for `thesis_bearing`, now also true of the cold-open pick.

**In practice: the first episode on a fresh subject costs ~10 minutes** (the
one-time section-tagging pass plus both per-episode acts); **each subsequent
episode from the same subject costs ~5** (section tagging already done).

`SOURCING.md`'s five-minute figure needs this same three-bucket correction, not
just a bigger single number. That cost is the product, not overhead: it is the
act that makes two episodes from one claim pool different.

---

## 6. Open

- `EpisodeClaim.position` under this architecture is the same sequence as
  `date_anchor` order, so it is redundant here. It may become the field that
  records movement boundaries. Undecided.
- `record_forward` is unwritten, and it is the only other architecture the data
  supports.
- Every number here should be revisited after the first rendered episode.
