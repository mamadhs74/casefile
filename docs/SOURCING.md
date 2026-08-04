# Stage 1 — Research & Scripting Spec (revised)

**Supersedes:** the original "retell the case with slight variation" approach.

## Why this changed

The original design — take a well-documented case writeup and vary the telling
slightly — fails on two independent grounds:

1. **Copyright.** Facts are not protected; *expression* is. A lightly reworded article
   is a derivative work. Varying phrasing does not create ownership, it creates
   exposure.
2. **Platform policy.** YouTube's inauthentic-content policy names "readings of
   material you did not create" as a violation example. The rewrite approach is
   the thing being described.

The fix is not to reword harder. It is to invert the flow: **gather facts from primary
sources into a structured claim table, then write original narration from the table.**
The narration never sees the source prose, so it cannot mirror it. This is a
structural guarantee, not a discipline problem.

---

## Source tiers

### Tier A — citable, narratable
Facts drawn from these may enter the claim table and be narrated.

- Court records, indictments, judgments, sentencing documents
- Inquest and coroner reports
- Police reports where lawfully public
- Contemporaneous newspaper reporting (for *what was reported when* — a fact about
  the record, distinct from a fact about the case)
- Government and archive holdings; national/state archive scans
- Public-domain works (check jurisdiction and date carefully)
- Academic and forensic literature
- Named on-record interviews conducted by you

### Tier B — leads only
May be used to *find* Tier A sources. **May never be a source ID on a claim, and its
prose may never inform narration phrasing.**

- Wikipedia and reference wikis
- Modern journalism behind the case
- Books about the case

Rule: if a Tier B source is the only thing supporting a claim, the claim does not go
in the episode. Either find the Tier A source it drew from, or cut the detail.

### Tier C — excluded entirely
Never read, never ingested, never used.

- Other creators' video scripts, transcripts, or auto-captions
- Podcast transcripts
- Content-farm article aggregators
- Anything whose value is its *telling* rather than its record

Tier C exclusion is enforced at the fetch layer with a domain blocklist, not by
convention.

---

## The claim table

Stage 1's primary artifact. Not prose — structured records.

```json
{
  "claim_id": "c017",
  "assertion": "The mill's key was reported missing several days before the killings.",
  "type": "fact | contemporaneous_report | disputed | inference",
  "sources": ["src_004"],
  "confidence": "established | reported | contested",
  "date_anchor": "1922-03-28",
  "entities": ["e02"],
  "narratable": true
}
```

Requirements:

- Every claim carries at least one Tier A source ID.
- `type` distinguishes *what happened* from *what was reported to have happened*.
  This distinction is most of what separates responsible true crime from the rest,
  and it is also where the interesting material lives.
- `confidence: contested` claims must be narrated as contested. The script generator
  is prompted with this field and cannot flatten it.
- Unsourced claims are droppable, not fixable. No "widely believed" filler.

## The entity table

```json
{
  "entity_id": "e02",
  "name": "...",
  "role": "victim | suspect | witness | investigator | commentator",
  "living": false,
  "adjudicated": true,
  "image_rights": "public_domain | licensed | none"
}
```

`living: true` on any entity trips **R8** and blocks render pending review.
`image_rights: none` blocks that entity from appearing in stage 3 shot selection.

---

## Editorial thesis — required, human-authored

A free-text field you write. Not generated. Render fails if empty.

It answers: **what is this episode arguing?** Not what happened — what you are
claiming about what happened, or about the record, or about how the case was handled.

Examples of a thesis that works:
- "The investigation failed because jurisdictional boundaries meant no single force
  owned the case."
- "The contemporary press coverage invented three details that are still repeated as
  fact today."
- "This case is famous for the wrong reason; the interesting part is the forensic
  method it accidentally pioneered."

Examples that fail:
- "A horrifying unsolved murder." (topic, not thesis)
- "Six people died mysteriously." (summary, not argument)

This single field is the difference between an original production and a content farm
output. It costs you two minutes per episode and it is the cheapest compliance
artifact in the system. It is also, not coincidentally, what makes the videos worth
watching.

---

## Script generation

Input: claim table + entity table + thesis + selected architecture.
**Not** input: any source document text.

The generator is instructed to:
- Build the narrative around the thesis, not around chronology by default
- Preserve `type` and `confidence` distinctions in the language
- Attribute contemporaneous reports as reports
- Produce no claim absent from the claim table

Post-generation checks:
- Every factual sentence maps to a `claim_id` (unmapped sentences are flagged)
- Similarity check of output against Tier A source text — high similarity means the
  model reproduced rather than composed; regenerate
- Reading-level and pacing check against the architecture's target

---

## Variation manifest

Stage 1 selects an episode architecture. Architectures differ in **structure**, not
decoration:

| Architecture | Shape |
|---|---|
| `chronological` | events in order, resolution at end |
| `investigation_led` | follows the inquiry, not the crime |
| `record_forward` | built around a single document and what it reveals |
| `misconception` | states the popular version, then dismantles it |
| `open_question` | frames one unresolved point and examines evidence both ways |
| `context_first` | the place and period, with the case as consequence |

Rules:
- No architecture repeats within a rolling window of N episodes (start N = 4).
- Architecture selects the visual grammar and pacing profile in `compose.py`, so
  structural variation propagates into the render automatically.
- The manifest is versioned. Adding architectures over time is expected.

---

## Bucket-2 guard

Before render, the episode must pass:

- Cold open is not the most distressing moment in the episode
- No imagery whose function is shock rather than information
- The episode reaches a resolution, a stated open question, or a conclusion — not a
  cliffhanger engineered for the next upload
- The thesis is stated within the first 90 seconds

Implement as a checklist the pipeline surfaces at review time. Not automatable, and
that's fine — it's the same two-minute gate as the thesis.

---

## What stays fully automated

Everything else. Source retrieval, claim extraction with human confirmation, entity
resolution, TTS, alignment, shot selection, render, thumbnail, upload, analytics
ingestion, cross-platform scheduling.

The manual surface is: **pick the case, write the thesis, clear the guard checklist.**
Call it five minutes an episode. That five minutes is what keeps the other ninety-five
percent monetizable.
