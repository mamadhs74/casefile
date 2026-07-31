# Frontend brief — casefile

## What this is

A production console for one person making documentary videos about historical
criminal cases. Not a consumer app. Not a dashboard for executives. The operator
is the owner, works alone, and will spend hours a week in here.

The single job of the main screen: **decide which case to produce next.** Every
other screen serves that decision or executes on it.

This matters for the design. The user is not browsing, they are triaging. They
need to see, at a glance across thirty cases, which ones can earn money and which
are legally radioactive. Speed of scanning beats visual density.

---

## Stack

Vite + React 18 + TypeScript in `apps/web/`. Tailwind. TanStack Query for server
state. React Router. Framer Motion only if motion earns it.

API base URL from `VITE_API_URL`, defaulting to `http://localhost:8000`.

Generate the API client types from the backend's OpenAPI schema rather than
hand-writing interfaces — `openapi-typescript` against `http://localhost:8000/openapi.json`.
Hand-written types will drift from the Pydantic schemas within a week.

---

## Design direction

Read `/mnt/skills/public/frontend-design/SKILL.md` equivalent guidance: do the
two-pass process. Brainstorm a token system first — 4–6 named hex values, two or
three typefaces with defined roles, a layout concept, and one signature element.
Critique that plan against the "would I produce this for any project" test before
writing any code. Show me the plan before you build.

### The subject's own world

The material here is archival: case files, inquest records, evidence inventories,
index cards, folder tabs, retrieval slips, microfilm. Municipal and police
archives are *colour-coded systems* — the colour on a folder tab means something.
That is where colour should come from in this interface: it encodes state, it is
not decoration. A case's monetization tier and legal risk are the two most
important facts about it, so those are the two things colour should carry.

The operator asked for colourful. Take that seriously — this should not be a
grey admin panel. But colour that means something will read as more considered
than colour applied for mood.

### Explicitly forbidden

These are the defaults that show up regardless of brief. Do not use them:

- Cream background near `#F4F1EA` with a high-contrast serif display and a
  terracotta accent near `#D97757`.
- Near-black background with one acid-green or vermilion accent.
- Broadsheet layout: hairline rules, zero border radius, dense newspaper columns.

And the genre-specific clichés, which are worse because they are on-the-nose:

- Blood red. Police-tape yellow. Chalk outlines. Evidence markers. Redaction bars
  as decoration. Typewriter or "stencil" display faces. Anything resembling a
  "CASE CLOSED" stamp. Manila-folder brown as the primary surface.

The subject is documentary journalism, not a true-crime podcast cover.

### Quality floor, not announced

Responsive to mobile. Visible keyboard focus on every interactive element.
`prefers-reduced-motion` respected. Colour never the only carrier of meaning —
every tier badge needs a label or shape alongside its colour, because red/green
is the most common colour-blindness axis and tier is the most important signal
in the product.

---

## Sections

Four top-level sections. Build the navigation shell for all four. Only the first
has a backend.

### 1. Cases — fully functional

The main screen. Everything else is secondary.

**Library view.** All cases from `GET /cases`. Each case shows title, year,
country, case type, resolution status, documentation score, and — prominently —
monetization tier and legal risk. Filter by status, tier, and case type via the
query parameters the endpoint already accepts. Paginate with offset/limit; the
response carries a total count.

Sort or group so RED and HIGH-risk cases are visually separated from the
producible ones. The operator should never accidentally start work on a case that
cannot earn.

**Case detail.** Full record, plus its sources, plus the R1 gate result from
`GET /cases/{id}/gate`. The gate result is the answer to "can I write this yet"
and should read as a status, not a form field: how many verified sources, how many
primary records, how many distinct domains, and which of the three conditions are
failing.

**New case form — this is the signature interaction.**

As the operator fills the form, `POST /cases/preview-eligibility` on debounce and
show the resulting tier live, before anything is saved. Toggle `child_victim` and
watch the tier drop to RED with the reason spelled out. Set the event year to
2019 and watch it fall to YELLOW.

This makes an invisible policy model visible and immediate, and it is the one
moment in this product worth spending real design attention on. The tier display
should feel like a verdict arriving, not a form field updating. That is the
signature element — build the rest quietly around it.

The form must never send `monetization_tier`, `legal_risk`, or
`eligibility_notes`. The API rejects them and the server computes them. Do not
add fields for them.

**Sources.** List and add via `GET`/`POST /cases/{id}/sources`. Adding a source
accepts a dropped file or a pasted URL onto a drop zone. Do not send a `domain`
field — the server derives it. After adding, re-fetch the gate so the operator
sees the effect immediately.

### 2. Studio — shell only

Where script, voice, and video generation will live. Build the route and an empty
state that names what is missing: no script generation, no voice synthesis, no
rendering yet. Do not mock a voice picker with fake voices. Do not draw a fake
waveform.

### 3. Publishing — shell only

Where uploads and per-platform metadata will live. Empty state naming YouTube,
TikTok, and Instagram as unbuilt targets.

### 4. Analytics — shell only

Where retention curves and cross-platform comparison will live. Empty state
explaining that metrics arrive after the first publish.

---

## Empty and error states

An empty screen is an invitation to act, not an apology. "No cases yet — add the
first one" with the action attached, not "Nothing to display."

Errors say what happened and what to do. The API returns a 422 with the
eligibility notes attached when a case is ineligible for production — surface
those notes as the message, since they are already written for a human.

Never a bare spinner where a skeleton would do, and never a spinner that covers
content already on screen.

---

## Copy

Active voice, sentence case, the operator's vocabulary rather than the schema's.
The interface says "sources" and "cases" because those are real words in this
domain. It should not say "entity" or "record" or "submit".

An action keeps its name through the flow: the button that says "Add source"
produces a confirmation that says "Source added."
