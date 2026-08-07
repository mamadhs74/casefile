"""The `chronological` architecture's script generator -- docs/ARCHITECTURES.md
v2 sec 3. Step 2 of the build: the six-section structure. Step 1 (episode_id
in, the render gate, rules 6/7, the narratable re-check) is unchanged in
spirit; this rewrite replaces its flat `str` output with `SectionedScript`
and adds cold-open validation, claim-to-section allocation, and rule 4's
word-count report.

Section content is still concatenation, not composition -- a claim's own
`statement`, one per line, never rewritten. Rule 4 (section word counts
within +-15% of budget) is checked and reported on `SectionedScript`, not
enforced: a concatenated claim statement is whatever extraction produced,
never a budget-length composition, so raising on it here would make this
function permanently unable to succeed on any real input until real
composition exists. That's step 3, not this one. Return emits
`Episode.thesis` verbatim as a visible placeholder for the same reason --
"paraphrased, not restated verbatim" (sec 3, S6) needs composition this
step doesn't have; verbatim is at least honestly not the real thing,
rather than silently passing off concatenation as paraphrase.

Ground and Resolution claims are identified by `Claim.section` -- see that
field's own docstring for why null means Sequence rather than a third
enum value, and why the ambiguity between "explicitly Sequence" and "not
yet reviewed" is a deliberate, reported tradeoff, not an oversight. This
module reports the untagged count on `SectionedScript` rather than
treating it as an error, per that same design.

The cold-open claim is a special case, not a fourth section: it must
appear in exactly Cold Open and Sequence (rule 2), never also in Ground or
Resolution -- so it is excluded from Ground/Resolution allocation and
forced into Sequence regardless of its own `Claim.section` tag, even if
that tag is GROUND or RESOLUTION. ARCHITECTURES.md doesn't spell this
case out explicitly; this is the one place this module makes a call the
spec leaves implicit, and it does so in the direction rule 2's "exactly
twice" literally requires.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from packages.db.models import Claim, Episode, EpisodeClaim, VariationProfile
from packages.domain.enums import Section

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

# docs/ARCHITECTURES.md sec 2: "Target: 20 minutes... derived, not fixed."
# Only narration_wpm varies (per VariationProfile, per episode); the
# 20-minute target and the six section shares below are fixed by the spec.
EPISODE_TARGET_MINUTES = 20
COLD_OPEN_SHARE = 0.04
THESIS_SHARE = 0.025
GROUND_SHARE = 0.10
SEQUENCE_SHARE = 0.65
RESOLUTION_SHARE = 0.14
RETURN_SHARE = 0.045


@dataclass(frozen=True)
class SectionWordCounts:
    """One instance holds actual counts, another holds budgeted counts --
    same shape, so a caller can zip the two and see the gap per section
    without this module deciding what counts as "close enough" (rule 4
    is reported, not enforced, at this step)."""

    cold_open: int
    thesis: int
    ground: int
    sequence: int
    resolution: int
    return_: int


@dataclass(frozen=True)
class SectionedScript:
    """docs/ARCHITECTURES.md sec 3's six sections, plus the two reports
    this step owes without enforcing: actual vs. budgeted word counts
    (rule 4) and how many of the episode's claims were untagged (neither
    GROUND nor RESOLUTION, i.e. Sequence by default -- see Claim.section's
    own docstring for why that's not necessarily the same as "reviewed
    and confirmed Sequence")."""

    cold_open: str
    thesis: str
    ground: str
    sequence: str
    resolution: str
    return_: str
    actual_word_counts: SectionWordCounts
    budgeted_word_counts: SectionWordCounts
    untagged_claim_count: int

    @property
    def text(self) -> str:
        return "\n\n".join(
            [self.cold_open, self.thesis, self.ground, self.sequence, self.resolution, self.return_]
        )


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


class VariationProfileNotFoundError(Exception):
    """Episode.variation_profile_id is NOT NULL but, like every FK in this
    codebase's actual running connections, not enforced at runtime -- see
    Episode.cold_open_claim_id's own docstring for the confirmed-empirically
    version of this. Needed here because rule 4's budget derives from
    VariationProfile.narration_wpm; not named in the approved design, added
    because generation cannot proceed without it."""

    def __init__(self, episode_id: int, variation_profile_id: int) -> None:
        self.episode_id = episode_id
        self.variation_profile_id = variation_profile_id
        super().__init__(
            f"episode {episode_id} references variation_profile "
            f"{variation_profile_id}, which does not exist"
        )


class ClaimNotNarratableError(Exception):
    """Defense in depth, not the only guard: EpisodeClaim.before_insert
    already rejects a non-narratable claim at the point it's added to an
    episode, but Claim.before_update lets narratable flip back to False
    afterward with no check at all. Re-checked here at generation time,
    the point where a claim degraded after insertion would otherwise
    reach a script unnoticed."""

    def __init__(self, claim_id: int) -> None:
        self.claim_id = claim_id
        super().__init__(f"claim {claim_id} is not narratable -- flip it by hand first")


class NoColdOpenClaimError(Exception):
    """docs/ARCHITECTURES.md sec 3.1: the cold open cannot be empty.
    Episode.cold_open_claim_id is nullable at the schema level (nothing
    stops an Episode existing before a cold open is chosen), but
    generation requires one."""

    def __init__(self, episode_id: int) -> None:
        self.episode_id = episode_id
        super().__init__(f"episode {episode_id} has no cold_open_claim_id set")


class ColdOpenClaimNotFoundError(Exception):
    """Episode.cold_open_claim_id's FK is declarative only -- see that
    field's own docstring. This is the check the column itself cannot
    perform: the referenced claim id does not exist at all."""

    def __init__(self, episode_id: int, claim_id: int) -> None:
        self.episode_id = episode_id
        self.claim_id = claim_id
        super().__init__(
            f"episode {episode_id}'s cold_open_claim_id {claim_id} does not exist"
        )


class ColdOpenClaimNotInEpisodeError(Exception):
    """The referenced claim exists, but was never added to this
    episode's own EpisodeClaim set -- a real claim, wrong episode."""

    def __init__(self, episode_id: int, claim_id: int) -> None:
        self.episode_id = episode_id
        self.claim_id = claim_id
        super().__init__(
            f"episode {episode_id}'s cold_open_claim_id {claim_id} "
            "is not in this episode's claim set"
        )


class ColdOpenClaimNotThesisBearingError(Exception):
    """docs/ARCHITECTURES.md sec 3.1: the cold open must be one of the
    thesis-bearing claims -- picking from the whole pool would give the
    same answer every time, which is the failure sec 4 exists to prevent."""

    def __init__(self, episode_id: int, claim_id: int) -> None:
        self.episode_id = episode_id
        self.claim_id = claim_id
        super().__init__(
            f"episode {episode_id}'s cold_open_claim_id {claim_id} is not thesis-bearing"
        )


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
) -> SectionedScript:
    """Checks run in this order: episode exists; render gate (rule 8);
    variation profile exists (rule 4's budget needs narration_wpm);
    per-claim narratable (defense in depth); thesis-bearing count (rule
    6); total claim count (rule 7, against min_claim_count); cold open
    (must be set, must exist, must be in this episode's claim set, must
    be thesis-bearing) -- deliberately last among the checks, since "must
    be thesis-bearing" only means anything once rule 6 has already
    passed. Only after all of that does section allocation and word-count
    reporting happen -- nothing here is computed from a claim set that
    hasn't already passed every other check.
    """
    episode = session.get(Episode, episode_id)
    if episode is None:
        raise EpisodeNotFoundError(episode_id)

    if not episode.thesis:
        raise EpisodeNotRenderableError(episode_id, "thesis is empty")
    if episode.architecture is None:
        raise EpisodeNotRenderableError(episode_id, "architecture is not set")
    thesis = episode.thesis

    profile = session.get(VariationProfile, episode.variation_profile_id)
    if profile is None:
        raise VariationProfileNotFoundError(episode_id, episode.variation_profile_id)

    rows = list(
        session.exec(
            select(EpisodeClaim, Claim)
            .select_from(EpisodeClaim, Claim)
            .where(EpisodeClaim.episode_id == episode_id, Claim.id == EpisodeClaim.claim_id)
        )
    )

    for _, claim in rows:
        if not claim.narratable:
            assert claim.id is not None
            raise ClaimNotNarratableError(claim.id)

    thesis_bearing_count = sum(1 for episode_claim, _ in rows if episode_claim.thesis_bearing)
    if not (MIN_THESIS_BEARING_CLAIMS <= thesis_bearing_count <= MAX_THESIS_BEARING_CLAIMS):
        raise ThesisBearingCountError(
            episode_id, thesis_bearing_count, MIN_THESIS_BEARING_CLAIMS, MAX_THESIS_BEARING_CLAIMS
        )

    if len(rows) < min_claim_count:
        raise InsufficientClaimCountError(episode_id, len(rows), min_claim_count)

    # Cold-open validation runs after rules 6/7, deliberately: "must be
    # thesis-bearing" is only a meaningful check once the thesis-bearing
    # set itself has already passed rule 6 -- checking it first would
    # make rule 6's own failure unreachable in isolation (there would be
    # no valid thesis-bearing claim to point a cold open at while also
    # testing "0 thesis-bearing claims").
    if episode.cold_open_claim_id is None:
        raise NoColdOpenClaimError(episode_id)

    cold_open_claim = session.get(Claim, episode.cold_open_claim_id)
    if cold_open_claim is None:
        raise ColdOpenClaimNotFoundError(episode_id, episode.cold_open_claim_id)

    cold_open_episode_claim = next(
        (ec for ec, c in rows if c.id == cold_open_claim.id), None
    )
    if cold_open_episode_claim is None:
        assert cold_open_claim.id is not None
        raise ColdOpenClaimNotInEpisodeError(episode_id, cold_open_claim.id)
    if not cold_open_episode_claim.thesis_bearing:
        assert cold_open_claim.id is not None
        raise ColdOpenClaimNotThesisBearingError(episode_id, cold_open_claim.id)

    # Section allocation. The cold-open claim is excluded here regardless
    # of its own Claim.section tag -- see module docstring -- and appended
    # to sequence_claims below instead, so it lands in exactly Cold Open
    # and Sequence (rule 2), never also in Ground or Resolution.
    ground_claims: list[Claim] = []
    resolution_claims: list[Claim] = []
    sequence_claims: list[Claim] = []
    untagged_claim_count = 0

    for _, claim in rows:
        if claim.section is None:
            untagged_claim_count += 1
        if claim.id == cold_open_claim.id:
            continue
        if claim.section == Section.GROUND:
            ground_claims.append(claim)
        elif claim.section == Section.RESOLUTION:
            resolution_claims.append(claim)
        else:
            sequence_claims.append(claim)

    sequence_claims.append(cold_open_claim)

    def _sort_key(claim: Claim) -> tuple[bool, str, int]:
        assert claim.id is not None
        return (claim.date_anchor is None, claim.date_anchor or "", claim.id)

    ground_claims.sort(key=_sort_key)
    resolution_claims.sort(key=_sort_key)
    sequence_claims.sort(key=_sort_key)

    cold_open_text = _as_sentence(cold_open_claim.statement)
    ground_text = "\n".join(_as_sentence(c.statement) for c in ground_claims)
    sequence_text = "\n".join(_as_sentence(c.statement) for c in sequence_claims)
    resolution_text = "\n".join(_as_sentence(c.statement) for c in resolution_claims)
    return_text = thesis

    total_words = round(EPISODE_TARGET_MINUTES * profile.narration_wpm)
    budgeted_word_counts = SectionWordCounts(
        cold_open=round(total_words * COLD_OPEN_SHARE),
        thesis=round(total_words * THESIS_SHARE),
        ground=round(total_words * GROUND_SHARE),
        sequence=round(total_words * SEQUENCE_SHARE),
        resolution=round(total_words * RESOLUTION_SHARE),
        return_=round(total_words * RETURN_SHARE),
    )
    actual_word_counts = SectionWordCounts(
        cold_open=_word_count(cold_open_text),
        thesis=_word_count(thesis),
        ground=_word_count(ground_text),
        sequence=_word_count(sequence_text),
        resolution=_word_count(resolution_text),
        return_=_word_count(return_text),
    )

    return SectionedScript(
        cold_open=cold_open_text,
        thesis=thesis,
        ground=ground_text,
        sequence=sequence_text,
        resolution=resolution_text,
        return_=return_text,
        actual_word_counts=actual_word_counts,
        budgeted_word_counts=budgeted_word_counts,
        untagged_claim_count=untagged_claim_count,
    )


def _as_sentence(statement: str) -> str:
    text = statement.strip()
    if not text.endswith((".", "!", "?")):
        text += "."
    return text


def _word_count(text: str) -> int:
    return len(text.split())
