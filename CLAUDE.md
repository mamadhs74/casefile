# casefile

Automated documentary video production system for well-documented criminal cases and
historical horror events. Research → script → shot list → voiceover → render → publish →
analytics, with human editorial checkpoints at two fixed gates.

Owner: mamadhs74. Target platform: macOS (Apple Silicon), local-first.

---

## Non-negotiable rules

These exist because of platform monetization policy, not preference. Do not "simplify"
them away.

### R1 — Source diversity gate
No script may be generated from fewer than **3 independent sources**, at least one of
which is a primary/public record (court filing, police report, inquest, contemporaneous
news archive). Sources are stored with URL, publisher, retrieval date, and a hash of the
extracted text. `ScriptGenerator` raises `InsufficientSourcesError` if the gate fails.
Reason: YouTube's inauthentic content policy explicitly names "readings of material you
did not create" as a violation. Facts are not copyrightable; expression is. We synthesize
facts from multiple sources and write original prose. We never paraphrase a single article.

### R2 — Structural variation is enforced, not optional
The renderer must not produce the same skeleton twice. A `VariationProfile` is sampled per
episode and controls: cold-open style (4 variants), act count (3–5), narration pacing
(WPM band), shot-duration distribution, transition vocabulary, music presence/absence,
subtitle style, and thumbnail composition. A `similarity_check` step compares the new
episode's structural fingerprint against the last 10 published; >0.85 similarity blocks
the render. Reason: "easily replicable at scale" is the literal wording of the policy.

### R3 — Two human gates
- **Gate A** (after script): you read and edit the script. Nothing renders until you
  approve. Edits are logged — they are the evidence of editorial control.
- **Gate B** (after render): you watch the cut and approve before publish.
Everything between and around the gates is automated. "Fully automated" means you make
two decisions per episode, not zero.

### R4 — Documentary register, not sensationalism
Tone target is factual/investigative. The style guide forbids: gore description beyond
what a news report would carry, speculation presented as fact, victim-blaming framing,
recreations of the moment of death, and "you won't believe what happened next" hooks.
Jan 2026 guideline updates monetize documentary treatment of crime; April 2026 updates
specifically demonetize sensationalized true crime. This is the difference between full
ads and no ads.

### R5 — Disclosure and self-certification
Every upload sets YouTube's altered/synthetic content flag where synthetic narration or
generated imagery is used, and completes self-certification conservatively. Overrating is
cheap; a pattern of underrating puts YPP eligibility under review.

### R6 — Asset licensing
Every audio and image asset carries a `license` field and a `source_url`. Allowed:
YouTube Audio Library, CC0, public domain, licenses we hold, generated assets.
`AssetStore.add()` rejects anything without a license record. No exceptions, no "probably
fine."

### R7 — Living victims and named individuals
Cases involving people who are alive and not public figures require extra care: no
unproven accusations, no addresses or identifying detail, no contact information.
Prefer cases that are legally resolved and historically distant.

---

## Architecture

```
casefile/
├── apps/
│   ├── api/                  FastAPI backend
│   └── web/                  React + Vite + TS frontend
├── packages/
│   ├── research/             source discovery, extraction, fact reconciliation
│   ├── script/               narrative generation, style guide, variation profiles
│   ├── voice/                TTS providers, voice registry, preview
│   ├── subtitle/             forced alignment, ASS styling
│   ├── visual/               shot list → imagery → ffmpeg filter graphs
│   ├── thumbnail/            composition, text layout, A/B variants
│   ├── publish/              per-platform adapters
│   └── analytics/            ingestion, normalization, attribution
├── data/
│   ├── casefile.db           SQLite
│   ├── cases/                the case library
│   └── renders/              working + output media
└── CLAUDE.md
```

### Stack
- Python 3.12, managed with `uv`. FastAPI + SQLModel + SQLite (Postgres later if needed).
- ffmpeg via subprocess with explicit filter graphs. **Not MoviePy** — on a MacBook Air
  the memory profile matters and MoviePy holds frames in RAM. Ken Burns is `zoompan`,
  crossfades are `xfade`, subtitle burn-in is `ass`.
- `faster-whisper` (or WhisperX) for word-level forced alignment against the generated
  narration, producing exact subtitle timings rather than estimates.
- React 18 + Vite + TypeScript + Tailwind + Framer Motion.
- Job queue: SQLite-backed `jobs` table + an asyncio worker process. No Redis, no Celery
  until there is a reason.

### Pipeline stages
Each stage is a pure-ish function with a typed input and output, persisted to the DB, and
independently re-runnable. A failed render must not require re-researching.

```
select_case → research → reconcile_facts → generate_script → [GATE A]
→ shot_list → generate_visuals → synthesize_voice → align_subtitles
→ compose_video → generate_thumbnail → [GATE B] → publish → track
```

---

## Platform notes

**YouTube Data API v3** — upload costs ~1600 quota units against a 10,000/day default,
so roughly 6 uploads/day before requesting an increase. Analytics is a separate API
(YouTube Analytics & Reporting) with its own quota. Verify current numbers in the console;
do not hardcode assumptions.

**TikTok Content Posting API** — requires a separate manual audit. Pre-audit, all posts
are SELF_ONLY. Review is manual with no expedited path. Submit the audit application in
week one so it runs in parallel with the build. Requires a real privacy policy URL and a
demo video of the app. `video.publish` scope for direct post, `video.upload` for
draft-to-inbox. No watermarks or promotional overlays added to content — that fails audit.

**Instagram** — Reels publishing goes through the Instagram Graph API and requires a
Business or Creator account linked to a Facebook Page. Insights come from the same API.

Every publish adapter implements the same interface and returns a `PublishResult` with a
platform post ID, so analytics can join back to the episode.

---

## Analytics model

The point is answering "which video, on which platform, performed how, and why." Store
time-series snapshots, not just current totals — retention curves and 24h/7d/30d velocity
are what actually inform the next episode.

Per episode/platform, track: impressions, CTR, views, average view duration, retention
curve, subscriber delta, and revenue where exposed. Join against the `VariationProfile`
so the system can eventually report which structural choices correlate with retention.
That correlation is the real product.

---

## Conventions

- Type hints everywhere. `ruff` + `mypy` clean before commit.
- Config in `.env`, never committed. `.env.example` stays current.
- No secrets, API keys, or tokens in the repo. Pre-commit hook checks for this.
- Tests for anything with branching logic. Rendering gets smoke tests, not pixel tests.
- Frontend: dark base, saturated accents, generous motion. Responsive down to tablet.
  Desktop-first — this is a production tool, not a phone app.
- Never delete or weaken a failing test to get a green suite. Fix the code, or leave it
  failing and say so. Removing the case is the one thing that must not happen.
- Never widen a type, add a permissive fallback, or relax an assertion to make an error
  go away. If the constraint is wrong, say why and ask.
- Never start a server on a port that may already be in use. Check with
  `lsof -ti:PORT` first, and if occupied, use a different port or ask. A failed bind
  is silent, and the requests then land on whatever is already running — which has
  already caused a write to the real database.
- Never issue POST, PATCH, or DELETE against a server you did not start yourself in
  this session.

## Commit style

Imperative mood. Subject under 50 characters, no trailing period, no emoji, no
conventional-commit prefixes. Body explains *why* when the why isn't obvious, wrapped at
72 characters. Write like you're explaining to someone who will `git blame` this line in
two years.

Banned words in commit messages: comprehensive, robust, seamless, leverage, enhance,
delve, powerful, cutting-edge, streamline. If a commit needs those words it's doing too
much and should be split.

Good:
```
Use zoompan instead of scale+crop for Ken Burns

scale+crop resampled every frame and pushed render time on a 20min
episode past 40 minutes. zoompan does the interpolation in one pass
and cut it to 11. Output is visually identical at 1080p.
```

```
Block renders that fingerprint above 0.85 similarity
```

Bad:
```
feat: Implement comprehensive video rendering pipeline ✨
Add robust error handling to enhance system reliability
Update files
```

One logical change per commit. If you can't write the subject line without "and", split it.
