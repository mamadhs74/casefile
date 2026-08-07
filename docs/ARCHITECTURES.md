# ARCHITECTURES.md

**Status: v1. Supersedes the earlier DRAFT.** Specifies `chronological` only.
`record_forward` is unwritten. `investigation_led`, `context_first`,
`misconception` and `open_question` are not buildable against the current data
layer — see `docs/SCHEMA.md` findings #16–#18.

Numbers in this document are arbitrary and cheap to change. Structure and rules
are not — they are what the generator is built against.

---

## 1. What `chronological` is

Events in the order they happened, with the thesis stated early and earned by the
end.

What makes an episode non-interchangeable is **not** the ordering. Date order is
the same for everyone. It is that the thesis decides **what gets time**. Two
episodes drawn from the same claim pool under this architecture differ because one
spends four minutes on the dress and thirty seconds on the verdict, and the other
does the reverse.

That mechanism is specified in §4. Without it, thesis is decorative and this
architecture produces one episode per claim pool.

---

## 2. Time budget

Target: **20 minutes**, narration at **150 words/minute** ≈ **3,000 words**.

| # | Section | Time | Words |
|---|---|---|---|
| 1 | Cold open | 0:45 | 110 |
| 2 | Thesis | 0:30 | 75 |
| 3 | Ground | 2:00 | 300 |
| 4 | Sequence | 13:00 | 1,950 |
| 5 | Resolution | 2:45 | 415 |
| 6 | Return | 1:00 | 150 |

Sequence at 65% is a deliberate claim: this architecture is mostly the events.

**Minimum claim count: 40** deduplicated claims for a 20-minute episode. Below
that, the generator should refuse rather than pad. (Arbitrary. Raise it after the
first real episode.)

---

## 3. Sections

### 1. Cold open
One claim, pulled out of order. The most concrete and physical claim available —
an object, a time, a distance, a wound, a sum of money. No names explained, no
orientation.

- Exactly one claim.
- Must also appear in Sequence at its correct chronological position.
- Never the verdict, never the outcome.

### 2. Thesis
`Episode.thesis`, stated plainly in the narrator's voice as a declarative
sentence. Not a question, not a tease.

If it cannot be said in two sentences it is not a thesis.

### 3. Ground
Who, where, when — the minimum needed to follow §4. Names, relationships, place,
year.

- No claim used here that Sequence will also use.
- If the claim table has no genuine setting material, this shrinks to 30 seconds
  of names and the time goes to Sequence.

### 4. Sequence — **the thesis mechanism**

Events in `date_anchor` order, broken into 3–5 movements. A movement break happens
at the largest date gaps in the claim set, not at a fixed count. Each movement
opens on its first claim with no transition sentence.

**Claims are marked thesis-bearing by hand.** When you select claims for an
episode, you flag the ones the thesis turns on. This is an editorial act, the same
shape as flipping `narratable` — a deliberate human write, inspectable afterward,
never inferred by a model.

Schema: `EpisodeClaim.thesis_bearing: bool`, default `False`.

**Per episode: 5–10 thesis-bearing claims.** Fewer than 5 and the thesis isn't
doing enough work to distinguish the episode. More than 10 and everything is
emphasised, which is the same as nothing being emphasised.

Word allocation inside Sequence:

- Thesis-bearing claims: **60%** of Sequence words, divided among them.
  At 8 claims that is ~145 words each — several sentences, with the detail, the
  number, the name, the physical specifics.
- All other claims: **40%**, divided among them. Roughly one sentence each,
  ~25–30 words. Stated and moved past.

The generator receives the thesis text and the flags. It does not decide which
claims matter; it decides only how to write the ones it was told matter.

### 5. Resolution
What the record settles, and what it doesn't. Verdict, outcome, aftermath.

- Unresolved threads are named as unresolved, once each, without speculation.

### 6. Return
Back to the thesis, now that the events have been laid out. Paraphrased, not
restated verbatim.

- No new claims. Every fact here appeared earlier.
- No moral. No address to the viewer.

---

## 4. Rules the generator enforces

A script failing any of these does not render.

1. All prose derives from claims in `EpisodeClaim`. No fact appears that isn't in
   the claim set.
2. The cold-open claim appears exactly twice: §1 and §4. Every other claim appears
   at most twice.
3. §6 introduces no claim id not already used.
4. Section word counts within ±15% of budget.
5. §4's claims are in `date_anchor` order with no exceptions.
6. §1 and §6 are non-empty, `Episode.thesis` is non-empty, `Episode.architecture`
   is non-null. **This is the render gate that `docs/SCHEMA.md` finding #13 says
   does not exist.**
7. Thesis-bearing count is between 5 and 10 inclusive.
8. Total claim count ≥ 40.

---

## 5. Open

- **`EpisodeClaim.position` under this architecture** is the same sequence as
  `date_anchor` order, so it is currently redundant here. It may become the field
  that records movement boundaries. Undecided.
- **`record_forward` is unwritten**, and it is the only other architecture the data
  supports.
- **Nothing here has been tested against a real claim table.** Every number above
  should be revisited after the first rendered episode.
