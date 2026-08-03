# Platform Policy Constraints

**Status:** binding on pipeline design
**Last verified:** 2026-08-04
**Re-verify:** quarterly, and after any platform policy announcement

This file exists because casefile's core requirement is monetized output. Platform
monetization policy is therefore a *hard constraint on architecture*, not a
publishing-time checklist. Several of the requirements below cannot be retrofitted
after the pipeline is built — they determine what stages 1 and 4 must produce.

---

## 1. The constraint that shapes everything: channel-level enforcement

YouTube evaluates inauthentic-content violations against the **channel as a whole** —
main theme, most-viewed videos, newest uploads, and metadata — not against individual
videos in isolation.

Engineering consequences:

- There is no per-video escape hatch. A batch of weak output contaminates the channel,
  including videos already earning.
- You cannot A/B test into compliance. By the time signal arrives, the channel is
  already the unit under review.
- Backfill is a liability. Publishing 30 episodes to "seed" a channel is the exact
  pattern that reads as a content farm.

**Design rule:** the pipeline must not be capable of emitting a large volume of
structurally similar episodes. Rate limiting and variation are safety features, not
product limitations.

---

## 2. YouTube — inauthentic content (clarified 2026-07-16)

The policy defines three buckets that are ineligible for YPP monetization:

### Bucket 1 — Generic, repetitive, or template-based
Material easily produced with AI, CGI, or templates, with little variation between
uploads. Explicitly includes AI-generated content built from generic templates that
adds no original insight or perspective, and readings of material the creator did not
write.

**Direct hit on casefile.** `compose.py` applying one Ken Burns treatment, one TTS
voice, and one subtitle style across every episode is a template with the topic
swapped. See §5 for required mitigations.

### Bucket 2 — Off-putting or distressing content
Content designed to be distressing or emotionally manipulative in order to chase
views. Channels dedicated to this are removed from YPP **regardless of whether the
content is AI-generated**.

**Direct hit on the horror/true-crime strategy.** This is the non-obvious one. The
genre is not banned — the *manipulative treatment* of it is. The distinction in
practice is whether the episode has a narrative and an argument, or whether it is
an escalating sequence of distressing beats engineered for retention.

Practical read: shock-forward cold opens, gore-adjacent imagery, and
retention-optimized cliffhanger stacking are the failure mode. Investigative framing,
historical context, and resolution are not.

### Bucket 3 — AI personas discussing sensitive topics
AI-generated representations of real people covering finance, legal, healthcare, or
medical subjects.

**Relevant to the celebrity strategy**, and to any case episode that ventures into
medical or legal analysis delivered by a synthetic presenter.

### What YouTube explicitly permits
- AI tooling inside an otherwise original production
- A synthetic voice narrating an original script (does not by itself require the
  altered-content disclosure)
- Reused intros and outros
- A recurring series where each episode covers its subject with real substance

The policy is **tool-agnostic**. AI use is not disqualifying. Mass production of
interchangeable output is.

### Disclosure
The altered/synthetic-content toggle in YouTube Studio is a *separate obligation* from
monetization eligibility. Disclosure does not reduce reach or monetization. It is
required when content makes a real person appear to say or do something they did not,
alters footage of a real event or place, or generates a realistic scene that did not
occur.

---

## 3. TikTok

- **AIGC label required** for content showing realistic-appearing people, places, or
  events that could pass as real. Enabling it does not reduce distribution.
- **Synthetic media depicting real private individuals is prohibited outright — even
  when labeled.** This is a hard blocker: no AI-generated or AI-altered imagery of
  victims, suspects, or witnesses in any case involving identifiable private people.
  Historical cases where all parties are long deceased are a different question but
  should still be treated conservatively.
- **Detection is automated.** TikTok runs C2PA Content Credentials, invisible
  watermarking, and detection models. Unlabeled AI content that the system identifies
  may be auto-labeled, distribution-limited, or removed.
- **Do not strip provenance metadata.** Attempting to evade detection through
  re-encoding or format conversion carries heavier penalties than voluntary
  disclosure. The pipeline must preserve C2PA data through the render chain.
- Creativity Program eligibility: 18+, 10,000 followers, 100,000 views in the
  trailing 30 days. Reported RPM roughly $0.20–$0.40 in US/FR — low enough that
  TikTok should be treated as a discovery surface, not a revenue line.

---

## 4. Meta (Facebook / Instagram)

- Originality requirement with an active unoriginal-content enforcement track;
  reposted or minimally-transformed material demonetizes a Page.
- AI Info label applies to photorealistic synthetic media and altered depictions of
  real people. AI-assisted captions, descriptions, hashtags, and text overlays are
  exempt.
- All new Facebook video uploads are treated as Reels.

---

## 5. Derived engineering requirements

Each of these is testable and should have a corresponding check in the pipeline.

| # | Requirement | Enforced at |
|---|---|---|
| R1 | Every episode carries a human-authored editorial thesis. Render fails without one. | stage 1 |
| R2 | Narration is composed from a structured claim table, never from a source document. | stage 1 |
| R3 | Every factual claim carries a source ID resolving to a Tier A source. | stage 1 |
| R4 | Episode architecture is selected from a variation manifest; no architecture repeats within a rolling window of N episodes. | stage 3 |
| R5 | Visual grammar (transition set, pacing profile, type treatment) varies per architecture. | `compose.py` |
| R6 | Voice selection varies across episodes within a strategy. | stage 2 |
| R7 | Per-platform disclosure flags are **required fields** in the upload payload schema, not optional. | stage 6 |
| R8 | Living-person gate: any named living individual triggers review before render. | stage 1 |
| R9 | No synthetic imagery depicting identifiable private individuals, on any platform. | stage 3 |
| R10 | C2PA metadata survives the ffmpeg chain; verify in render QA. | stage 5 |
| R11 | Publish rate limiter per channel. Backfill batches are blocked by default. | stage 6 |
| R12 | Each strategy publishes to its own channel set with its own visual and vocal identity. Templates are never shared across strategies. | config |

---

## 6. Open questions

- Where exactly is the bucket-2 line for true crime? No bright-line test exists.
  Working assumption: an episode must survive the question *"what is this episode
  arguing?"* If the only answer is "that something terrible happened," it fails.
- Does the celebrity-news strategy survive bucket 3 at all? Films-and-production
  facts are materially safer than person-focused news. Reassess before building it.
- Publicity rights and defamation exposure for living subjects are **separate from
  platform policy** and are not addressed in this document. Qualified legal advice
  needed before any episode covering a living, non-adjudicated subject.

---

## 7. Sources

Primary: YouTube channel monetization policies; Creator Insider (Matt Halprin,
2026-07); TikTok Creator Portal and AIGC labeling guidance; Meta creator monetization
policy. Secondary reporting: TechCrunch, 2026-07-20.

Verify against the platform help pages directly before relying on any line here.
Secondhand summaries drift.
