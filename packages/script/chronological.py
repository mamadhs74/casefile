"""The `chronological` architecture's script generator -- docs/ARCHITECTURES.md
v2. This is step 1 of the build: episode_id in, the render gate, and two of
the seven generation-time preconditions. Output is still flat concatenation
of each claim's own `statement` in date order -- no six-section structure,
no thesis-bearing word-weighting yet. That's step 2.

Input is `Episode` and its `EpisodeClaim` set, not a caller-supplied
subject_id/claim_ids pair -- thesis, architecture, and the claim selection
all come from the episode itself, not from arguments that could disagree
with any real `Episode` row.

Every claim reached through `EpisodeClaim` was narratable at the point it
was added to the episode -- `EpisodeClaim.before_insert`
(packages/db/listeners.py) guarantees that. This module does not re-check
it at generation time, which is a real gap worth naming rather than
silently carrying forward: `Claim.before_update` only validates a flip
*to* narratable=True, not away from it, so a claim's sourcing could be
degraded after it's already in an episode's claim set with nothing
noticing until generation, and this version still wouldn't notice then
either. The previous version of this module (subject_id/claim_ids
signature) re-checked narratable per claim as defense in depth; this
rewrite dropped that check rather than carry it forward unexamined into a
new signature -- not because the gap closed, but because re-adding it
wasn't part of this step's approved scope. Not fixed here.
"""

from __future__ import annotations

from sqlmodel import Session, select

from packages.db.models import Claim, Episode, EpisodeClaim

MIN_THESIS_BEARING_CLAIMS = 5
MAX_THESIS_BEARING_CLAIMS = 10

# Injectable, not a Strategy column. docs/ARCHITECTURES.md sec 2 calls every
# number in that document "arbitrary and cheap to change... revisit after
# the first rendered episode" -- unlike R1's gate thresholds (per-strategy,
# so they live on Strategy), this number is specific to one architecture,
# and there is no per-architecture config surface in the schema today.
# Promoting it to a DB column ahead of a second architecture that might
# need a different number isn't done here. Kept overridable per call
# instead, the same shape as SourceFetcher.fetch_source()'s own
# tier: SourceTier | None override -- satisfying this in a test means
# constructing real Claim rows through a five-listener-gated chain
# (Subject -> Source -> Claim -> ClaimSource -> narratable flip), real
# fixture cost, not a number worth hardcoding into every success-path test.
MIN_TOTAL_CLAIM_COUNT = 40


class EpisodeNotFoundError(Exception):
    def __init__(self, episode_id: int) -> None:
        self.episode_id = episode_id
        super().__init__(f"no episode with id={episode_id}")


class EpisodeNotRenderableError(Exception):
    """Rule 8 (docs/ARCHITECTURES.md sec 4, "render gate") and
    docs/SCHEMA.md finding #13: Episode.thesis must be non-empty and
    Episode.architecture must be non-null. Finding #13 named this gate as
    documented in SCHEMA.md and POLICY.md's R1 but never actually enforced
    anywhere in the codebase. This is that enforcement, not a duplicate of
    it -- there is still no persistence-layer listener for this; it only
    fires here, at generation time."""

    def __init__(self, episode_id: int, reason: str) -> None:
        self.episode_id = episode_id
        self.reason = reason
        super().__init__(f"episode {episode_id} is not renderable: {reason}")


class ThesisBearingCountError(Exception):
    """Rule 6: 5-10 thesis-bearing claims inclusive."""

    def __init__(self, episode_id: int, count: int, minimum: int, maximum: int) -> None:
        self.episode_id = episode_id
        self.count = count
        self.minimum = minimum
        self.maximum = maximum
        super().__init__(
            f"episode {episode_id} has {count} thesis-bearing claims, "
            f"need between {minimum} and {maximum} inclusive"
        )


class InsufficientClaimCountError(Exception):
    """Rule 7: total claim count >= the minimum. docs/ARCHITECTURES.md
    sec 2: "the generator refuses below 40 rather than padding." """

    def __init__(self, episode_id: int, count: int, minimum: int) -> None:
        self.episode_id = episode_id
        self.count = count
        self.minimum = minimum
        super().__init__(f"episode {episode_id} has {count} claims, need at least {minimum}")


def generate_script(
    session: Session,
    episode_id: int,
    *,
    min_claim_count: int = MIN_TOTAL_CLAIM_COUNT,
) -> str:
    """Checks run in this order: episode exists; render gate (rule 8);
    thesis-bearing count (rule 6); total claim count (rule 7, against
    min_claim_count -- see that constant's own comment for why it's
    injectable). Ordering of the output itself is unchanged from the
    previous version: date_anchor ascending, claims with no date_anchor
    last, claim id as the tiebreak. docs/ARCHITECTURES.md sec 6 (Open)
    already notes EpisodeClaim.position is redundant with date_anchor
    order for this architecture, so this still sorts by date_anchor
    directly rather than trusting position.
    """
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise EpisodeNotFoundError(episode_id)

    if not episode.thesis:
        raise EpisodeNotRenderableError(episode_id, "thesis is empty")
    if episode.architecture is None:
        raise EpisodeNotRenderableError(episode_id, "architecture is not set")

    rows = list(
        session.exec(
            select(EpisodeClaim, Claim)
            .select_from(EpisodeClaim, Claim)
            .where(EpisodeClaim.episode_id == episode_id, Claim.id == EpisodeClaim.claim_id)
        )
    )

    thesis_bearing_count = sum(1 for episode_claim, _ in rows if episode_claim.thesis_bearing)
    if not (MIN_THESIS_BEARING_CLAIMS <= thesis_bearing_count <= MAX_THESIS_BEARING_CLAIMS):
        raise ThesisBearingCountError(
            episode_id, thesis_bearing_count, MIN_THESIS_BEARING_CLAIMS, MAX_THESIS_BEARING_CLAIMS
        )

    if len(rows) < min_claim_count:
        raise InsufficientClaimCountError(episode_id, len(rows), min_claim_count)

    ordered = sorted(
        (claim for _, claim in rows),
        key=lambda c: (c.date_anchor is None, c.date_anchor or "", c.id),
    )

    lines = [_as_sentence(claim.statement) for claim in ordered]
    return "\n".join(lines)


def _as_sentence(statement: str) -> str:
    text = statement.strip()
    if not text.endswith((".", "!", "?")):
        text += "."
    return text
