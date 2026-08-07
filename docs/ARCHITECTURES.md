# ARCHITECTURES.md

**Status: v2.** Specifies `chronological` only. `record_forward` is unwritten.
`investigation_led`, `context_first`, `misconception` and `open_question` are not
buildable against the current data layer — see `docs/SCHEMA.md` findings #16–#18.

Changes from v1: word budget derives from `VariationProfile.narration_wpm` rather
than a hardcoded rate; cold open composes with `ColdOpenStyle`'s four variants
rather than superseding them; rules are split into generation-time and audit.

---

## 1. What `chronological` is

Events in the order they happened, with the thesis stated early and earned by the
end.

What makes an episode non-interchangeable is **not** the ordering. Date order is
the same for everyone. It is that the thesis decides **what gets time**. Two
episodes drawn from the same claim pool differ because one spends four minutes on
the dress and thirty seconds on the verdict, and the other does the reverse.

That mechanism is §4. Without it, thesis is decorative and this architecture
produces one episode per claim pool.

---

## 2. Time and word budget

Target: **20 minutes**. Word count is **derived, not fixed**:

```
total_words = 20 * VariationProfile.narration_wpm
```

At 145 wpm that is 2,900 words; at 160, 3,200. Section budgets are percentages of
whatever that total comes to.

| # | Section | Share | Time @20min |
|---|---|---|---|
| 1 | Cold open | 4% | 0:45 |
| 2 | Thesis | 2.5% | 0:30 |
| 3 | Ground | 10% | 2:00 |
| 4 | Sequence | 65% | 13:00 |
| 5 | Resolution | 14% | 2:45 |
| 6 | Return | 4.5% | 1:00 |

Sequence at 65% is a deliberate claim: this architecture is mostly the events.

**Minimum claim count: 40** distinct claims. Distinct, not merely present —
`docs/SCHEMA.md` records that claim extraction has no dedup, so a pool of 45 rows
may hold 8 facts. Until dedup exists this count must be eyeballed, and the
generator refuses below 40 rather than padding.

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
- It must also appear in Sequence at its correct chronological position.
- Never the verdict, never the outcome.
- No names explained, no orientation.

### 2. Thesis
`Episode.thesis`, stated plainly in the narrator's voice as a declarative
sentence. Not a question, not a tease. If it cannot be said in two sentences it is
not a thesis.

### 3. Ground
Who, where, when — the minimum needed to follow §4.

- No claim used here that Sequence will also use.
- If the claim table has no genuine setting material, this shrinks to 30 seconds
  of names and the time goes to Sequence.

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

Word allocation inside Sequence:

- Thesis-bearing claims: **60%**, divided among them. At 8 claims that is ~145
  words each — several sentences, with the detail, the number, the name, the
  physical specifics.
- All other claims: **40%**, divided among them. One sentence each, ~25–30 words.
  Stated and moved past.

The generator receives the thesis text and the flags. It does not decide which
claims matter; it decides only how to write the ones it was told matter.

### 5. Resolution
What the record settles, and what it doesn't. Verdict, outcome, aftermath.
Unresolved threads named as unresolved, once each, without speculation.

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
write the thesis, clear the guard checklist — five minutes.

This architecture adds a fourth act: **flag 5–10 thesis-bearing claims** from a
pool of 40+. Realistically another 3–5 minutes, and unlike `narratable` it does
not amortize — `thesis_bearing` lives on `EpisodeClaim`, so a second episode from
the same subject under a different thesis requires flagging again.

`SOURCING.md`'s five-minute figure should be corrected to ten. That cost is the
product, not overhead: it is the act that makes two episodes from one claim pool
different.

---

## 6. Open

- `EpisodeClaim.position` under this architecture is the same sequence as
  `date_anchor` order, so it is redundant here. It may become the field that
  records movement boundaries. Undecided.
- `record_forward` is unwritten, and it is the only other architecture the data
  supports.
- Every number here should be revisited after the first rendered episode.
