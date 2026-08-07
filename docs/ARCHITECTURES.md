# Episode architecture structural specs

**Status: DRAFT. Not reviewed, not approved, expected to be rewritten.**

Scope: the four `EpisodeArchitecture` values buildable against what automated claim
extraction can actually produce today — `chronological`, `investigation_led`,
`record_forward`, `context_first`. `misconception` and `open_question` are excluded on
purpose; see `docs/SCHEMA.md`'s Episode section for why (both need `DISPUTED`/`CONTESTED`
claims, which no automated extraction path can produce until cross-source reconciliation
exists).

`docs/SOURCING.md`'s variation manifest gives each architecture exactly one line — a
"Shape," not a structure. Everything below the Shape line, for all four architectures, is
this document's own invention, not a transcription of something already decided. Flagged
throughout, and summarized at the end, so nothing here gets mistaken for settled spec.

Two rules apply globally, from `docs/SOURCING.md`'s Bucket-2 guard, and are **not**
repeated per architecture below because they don't vary by architecture:
- The thesis is stated within the first 90 seconds.
- Cold open is not the most distressing moment in the episode; no imagery whose function
  is shock rather than information.

---

## `chronological` — events in order, resolution at end

### Ordered sections
1. **Cold open (0:00–0:30).** One concrete, specific detail from partway through the
   timeline — not the crime's worst moment, not the ending. Establishes place and time
   without resolving anything.
2. **Setup + thesis (0:30–1:30).** Who, where, when — then the thesis stated directly,
   framed as a lens for what's about to unfold in order ("watch how this sequence built
   toward X"), not as a claim to be proven later.
3. **Rising timeline (1:30–14:00).** The bulk. Claims in strict date order from the
   earliest reliably dated claim through the event itself.
4. **Aftermath (14:00–18:00).** What happened next, still moving forward in time — not a
   flashback structure.
5. **Resolution (18:00–19:30).** The case's actual current status, tied explicitly back
   to the thesis from section 2.
6. **Close (19:30–20:00).** Short editorial button. No cliffhanger.

### Thesis placement
Lands at the *late* edge of the 90-second window (around :60–:90), after enough setup
that the audience has a place and a family before being told what the ordering is meant
to show them. Framed forward-looking ("watch for X"), because the architecture's whole
mechanism is that order carries the argument — stating the payoff before the order
unfolds would pre-empt the one structural device this architecture has.

### Opening 30 seconds — must / must not
Must: ground a specific moment in place and time, using a claim with a real `date_anchor`.
Must not: state the thesis, name the eventual outcome, or open on the crime itself — the
cold open is deliberately mid-timeline, not the inciting or terminal event.

### Claim types needed, and the gap if they're missing
Needs `FACT` and `CONTEMPORANEOUS_REPORT` claims with usable `date_anchor` values, in a
sortable order. **Real gap, not hypothetical:** `docs/SCHEMA.md`'s Claim section is
explicit that `date_anchor` is free text — *"often only precise to a month or a
season"* — and that strict chronological sorting was deliberately left unbuilt (*"add a
separate nullable `sort_date`... rather than tightening this"*). That field doesn't exist.
Without it, "events in order" degrades to whatever order a human manually imposes at
`EpisodeClaim.position` — buildable, but not *computed* from the claim table the way the
Shape line implies.

### Rough 20-minute budget
Cold open 0:30 · setup+thesis 1:00 · timeline 12:30 · aftermath 4:00 · resolution 1:30 ·
close 0:30.

---

## `investigation_led` — follows the inquiry, not the crime

### Ordered sections
1. **Cold open (0:00–0:30).** The moment the investigation began — a call, a discovery,
   a question someone asked — not the crime itself.
2. **Thesis as investigative question (0:30–1:30).** Thesis frames what the investigation
   reveals about *process* (a method, an institutional failure, a missed signal), not
   "what happened."
3. **Investigative beats (1:30–15:00).** Structured by what investigators believed and
   when, which may present case facts out of event-order relative to when they actually
   occurred — organized by discovery order, not occurrence order.
4. **Turning point (15:00–17:00).** The moment the investigation's own trajectory
   changed — a suspect cleared, new evidence, a reopened file.
5. **Where the inquiry lands (17:00–19:00).** Current state: closed, cold, reopened.
6. **Close (19:00–20:00).**

### Thesis placement
Lands early in the window (around :30–:45) — this architecture's hook is the *question*
driving the investigation, so the audience needs the question before the setup detail
that chronological front-loads instead.

### Opening 30 seconds — must / must not
Must: open on an investigator's action or a piece of process (a search, a report filed),
using a `CONTEMPORANEOUS_REPORT` claim if one exists for that moment. Must not: open on
the crime scene, the victim, or any claim about what actually happened rather than what
was being investigated.

### Claim types needed, and the gap if they're missing
This is the best-supported of the four against what extraction actually produces:
`CONTEMPORANEOUS_REPORT` claims (what investigators/witnesses said or believed at the
time) contrasted against `FACT` claims (what was later established) map directly onto
this architecture's own mechanism — the type distinction *is* the "belief vs. established"
distinction the Shape line needs. No claim type gap here that isn't shared by the whole
system.

**Invented, and unresolved:** the ordering mechanism itself. "Discovery order" (when
investigators learned something) is not the same axis as `date_anchor` (when something
happened), and nothing in the schema captures the former — no field records when a claim
was *reported to* or *discovered by* investigators, separate from when the underlying
event occurred. Without it, this architecture's ordering has to be authored by hand, same
gap as chronological's `sort_date`, just for a different axis.

### Rough 20-minute budget
Cold open 0:30 · thesis 1:00 · investigative beats 13:30 · turning point 2:00 · where it
lands 2:00 · close 0:30.

---

## `record_forward` — built around a single document and what it reveals

### Ordered sections
1. **Cold open (0:00–0:30).** The document itself, as a physical/visual object — not the
   crime, not a person.
2. **Thesis as what the document unlocks (0:30–1:30).** States what this specific
   document establishes that popular retellings, built on secondary sources, miss or get
   wrong.
3. **Walk the document (1:30–16:00).** Moves through the document's own internal
   structure (an inquest's testimony order, a filing's sections), each claim anchored
   explicitly to its position within that one source.
4. **What the document doesn't say (16:00–18:00).** The document's own limits and
   silences — handled factually, not speculatively (CLAUDE.md's R4: no speculation
   presented as fact).
5. **Legacy (18:00–19:30).** What the document changed, or didn't, afterward.
6. **Close (19:30–20:00).**

### Thesis placement
Lands late (around :75–:90) — the audience needs to see the document itself first (cold
open) before the thesis can credibly claim it reveals something.

### Opening 30 seconds — must / must not
Must: visually and verbally establish the document as a specific, real, dated artifact.
Must not: summarize its contents yet — the reveal is the structure, not the cold open.

### Claim types needed, and the gap if they're missing
Needs a **minimum volume of claims from one single source** — not a claim-type
requirement so much as a claim-*concentration* requirement, since `ClaimSource` already
supports "which claims come from source X" directly. No threshold is specified anywhere
in the docs; I haven't invented one either, flagging that as a real open number someone
needs to set (ten claims from one source clearly isn't enough for 16 minutes of "walk the
document"; forty-five plausibly is). Checked against subject 8's own real claim table
from prior reads in this thread: `source_7` (Lizzie Borden, `CONTEMPORANEOUS`/Tier A) has
45 claims, all from that one source — this architecture is plausibly buildable against it
today, unlike the other three sources under that subject, which top out at 17 claims
each. Worth noting as the one architecture with a real positive data point already in
hand, not just a gap.

### Rough 20-minute budget
Cold open 0:30 · thesis 1:00 · document walk 14:30 · silences 2:00 · legacy 1:30 · close
0:30.

---

## `context_first` — the place and period, with the case as consequence

### Ordered sections
1. **Cold open (0:00–0:30).** The place and period itself — sensory, geographic, or
   historical framing. No crime yet, no names yet.
2. **Thesis (0:30–1:30).** States what about this specific place or period made the case
   possible, likely, or notable — an argument connecting context to consequence, not
   scene-setting for its own sake.
3. **Context build (1:30–10:00).** Historical, social, or economic background —
   established facts about the setting, independent of the case's own events.
4. **The case as consequence (10:00–17:00).** The event itself, told as the outcome the
   preceding context made possible.
5. **Legacy in context (17:00–19:00).** How the place or period changed, or didn't,
   afterward.
6. **Close (19:00–20:00).**

### Thesis placement
Lands at the same point as `record_forward` (around :75–:90) — the audience needs the
place/period established first, or "the case as consequence" has nothing to be a
consequence *of* yet.

### Opening 30 seconds — must / must not
Must: establish place and period with zero reference to the crime. Must not: name a
victim, suspect, or the crime itself — that's what section 4 exists to reveal as
*consequence*, and naming it early collapses the structure into `chronological`'s cold
open by another name.

### Claim types needed, and the gap if they're missing
Needs a real volume of `category = LOCATION` and `category = TIMELINE` claims (per
`ClaimCategory`, docs/SCHEMA.md's Claim section) that are about the *setting*, not the
case's own events, to sustain section 3 independently of section 4. I have not checked
this against subject 8's actual category breakdown — flagging as unverified, not
invented, since a category count is a real, checkable number I simply didn't pull this
turn.

### Rough 20-minute budget
Cold open 0:30 · thesis 1:00 · context build 8:30 · case as consequence 7:00 · legacy
2:00 · close 0:30.

---

## Where these collapse into each other

**`chronological` and `investigation_led` are not a collision risk — they are not
distinguishable at generation time today, full stop.** `EpisodeClaim` stores only
`episode_id`, `claim_id`, `position` — an untagged integer. Nothing records which axis a
given ordering represents, and nothing else in `Claim` does either: `claim_type`
(`FACT`/`CONTEMPORANEOUS_REPORT`) is epistemic, not temporal, and `date_anchor` describes
when the underlying event happened, not when it was discovered or reported. Two episodes
built from the same claim pool, one labeled `chronological` and one
`investigation_led`, can carry byte-identical `EpisodeClaim` rows — same `claim_id`s,
same `position` values — and nothing in the schema would notice. Today, the entire
difference between the two is narration language layered over one identical, untagged
ordering mechanism — `docs/POLICY.md`'s Bucket 1 failure exactly as named
(*"different wording over an identical skeleton is still the same skeleton"*), not a
risk of it happening. See `docs/SCHEMA.md`'s Episode section for the same finding
recorded there. **Effective count for this document: three architectures, not four.**

**`context_first` and `chronological` risk converging in their back half.** Once
`context_first` reaches section 4 ("the case as consequence"), it's narrating events
forward in time, same as `chronological`'s section 3 — the distinguishing work is
entirely front-loaded into section 3's context build. If that section is thin (which the
unverified category-count gap above could easily produce), the two architectures would
read nearly identically from the crime onward.

**`record_forward` is the structurally safest of the four.** Its organizing principle — a
single document's own internal order — doesn't resemble any of the other three's
event/discovery/context ordering, and it's the only one with a real, checked positive
data point (source_7's 45 claims) rather than an open question about whether the claim
table can support it.

## What I invented, because the docs don't say — consolidated

- Every section name, count, and boundary above. `docs/SOURCING.md` gives one phrase per
  architecture and nothing else.
- Where within the 90-second thesis window each architecture lands, and why — the docs
  only fix the outer bound, globally, not per architecture.
- Per-architecture opening-30-seconds content rules beyond the two global Bucket-2 rules.
- The minute-by-minute time budgets. `docs/SOURCING.md` references *"the architecture's
  target"* for reading-level and pacing as if such targets already exist; none are
  specified anywhere, for any architecture.
- `record_forward`'s minimum-claim-volume threshold — not given a number here either,
  flagged as still open rather than guessed at.
- The mapping of `ClaimCategory` values to which architecture's sections need them
  (`LOCATION`/`TIMELINE` for `context_first`'s context build, in particular) — a
  reasonable-seeming inference from the category names, not something either doc states.

## Schema dependencies this draft surfaces that don't exist yet

- A sortable date field (`chronological`), separate from free-text `date_anchor` —
  already named as a known gap in `docs/SCHEMA.md`'s Claim section.
- A discovery/reporting-order field, separate from event date (`investigation_led`) —
  not previously named anywhere; new to this document.
- A minimum-claims-per-source threshold, or some other computable readiness check, before
  `record_forward` is offered as a selectable architecture for a given subject.
