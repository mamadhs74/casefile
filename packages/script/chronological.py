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

from dataclasses import dataclass, replace

from sqlmodel import Session, select

from packages.db.models import Claim, Episode, EpisodeClaim, VariationProfile
from packages.domain.enums import Section
from packages.script.composition import word_count
from packages.script.composition_provider import ClaimForComposition

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

# docs/ARCHITECTURES.md sec 2 (rewritten): the 20-minute floor is
# withdrawn -- it assumed a ~145-word elaboration on thesis-bearing
# claims that three real Gemini runs never produced under rule 1 (never
# introduce a fact absent from the claims). Word budget now derives from
# claim count, not from a target runtime -- see WORDS_PER_CLAIM below.
# EPISODE_TARGET_MINUTES survives only as generate_script's
# episode_target_minutes parameter's default; nothing computes the
# budget from it anymore. See that parameter's own docstring.
EPISODE_TARGET_MINUTES = 20

# docs/ARCHITECTURES.md sec 2 (rewritten, second correction): actually
# measured, not asserted -- the 28 this constant previously held was a
# guess dressed up as a measurement, corrected here against the real
# numbers. Across two real Gemini runs where composed claim length is
# measurable, non-elaborated ("rest") claims ran 15.0-18.4 words;
# thesis-bearing claims ran 16.0-21.0 (see docs/HANDOFF.md sec 11, sec
# 7 findings #30-31). 18 is the top of the non-elaborated range, not
# above it -- with the 60/40 split removed (see _apply_word_targets),
# every claim gets the same non-elaborated treatment, so the
# non-elaborated range is the relevant one, not the thesis-bearing one.
# This number is expected to rise if a later prose pass adds connective
# tissue between claims (the two measured runs wrote each claim as its
# own plain sentence, nothing more) -- re-measure against real output
# when that pass exists rather than guess again.
WORDS_PER_CLAIM = 18

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
    and confirmed Sequence").

    cold_open_claim/ground_claims/sequence_claims/resolution_claims --
    additive, added for step 3's composition pass
    (packages/script/chronological_composition.py). Text fields above
    already existed and are computed the same way they always were
    (concatenation); these expose the *allocation* generate_script did to
    produce that text, as ClaimForComposition rather than raw Claim ORM
    objects specifically because thesis_bearing lives on EpisodeClaim,
    not Claim -- these have to be built while both rows are still in
    scope, which is only true inside generate_script's own allocation
    loop. Nothing about the existing text/word-count/untagged fields
    changes, and nothing here is a second implementation of allocation --
    it is the one implementation, exposed.

    derived_runtime_minutes -- additive, added when the word budget
    stopped being derived from a target runtime (episode_target_minutes)
    and started being derived from claim count (WORDS_PER_CLAIM). Rule 4
    used to report actual-vs-budgeted words against a target that was
    also a runtime by construction (minutes x wpm); now that the budget
    is claims x words/claim, nothing reports what runtime that word
    count actually implies unless this field does it. total_words /
    narration_wpm, unrounded -- a report, not a target; nothing
    downstream enforces it."""

    cold_open: str
    thesis: str
    ground: str
    sequence: str
    resolution: str
    return_: str
    actual_word_counts: SectionWordCounts
    budgeted_word_counts: SectionWordCounts
    derived_runtime_minutes: float
    untagged_claim_count: int
    cold_open_claim: ClaimForComposition
    ground_claims: list[ClaimForComposition]
    sequence_claims: list[ClaimForComposition]
    resolution_claims: list[ClaimForComposition]

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
    episode_target_minutes: int = EPISODE_TARGET_MINUTES,
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

    episode_target_minutes is kept as a parameter but no longer feeds
    the word budget (docs/ARCHITECTURES.md sec 2, rewritten): the budget
    is now claims x WORDS_PER_CLAIM, because a target runtime implies a
    word count that assumes an elaboration rate three real Gemini runs
    never produced -- see WORDS_PER_CLAIM's own comment. The parameter
    stays for callers that still pass it (chronological_composition.py,
    the scratch scripts); it is otherwise inert. What used to be an
    input is now an output instead -- derived_runtime_minutes on the
    return value reports the runtime that many words actually implies.
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
    ground_claims: list[ClaimForComposition] = []
    resolution_claims: list[ClaimForComposition] = []
    sequence_claims: list[ClaimForComposition] = []
    untagged_claim_count = 0

    for episode_claim, claim in rows:
        if claim.section is None:
            untagged_claim_count += 1
        if claim.id == cold_open_claim.id:
            continue
        composable = _to_claim_for_composition(claim, episode_claim)
        if claim.section == Section.GROUND:
            ground_claims.append(composable)
        elif claim.section == Section.RESOLUTION:
            resolution_claims.append(composable)
        else:
            sequence_claims.append(composable)

    cold_open_composable = _to_claim_for_composition(cold_open_claim, cold_open_episode_claim)
    sequence_claims.append(cold_open_composable)

    def _sort_key(c: ClaimForComposition) -> tuple[bool, str, int]:
        return (c.date_anchor is None, c.date_anchor or "", c.claim_id)

    ground_claims.sort(key=_sort_key)
    resolution_claims.sort(key=_sort_key)
    sequence_claims.sort(key=_sort_key)

    cold_open_text = _as_sentence(cold_open_composable.statement)
    ground_text = "\n".join(_as_sentence(c.statement) for c in ground_claims)
    sequence_text = "\n".join(_as_sentence(c.statement) for c in sequence_claims)
    resolution_text = "\n".join(_as_sentence(c.statement) for c in resolution_claims)
    return_text = thesis

    # docs/ARCHITECTURES.md sec 2 (rewritten): claims x WORDS_PER_CLAIM,
    # not episode_target_minutes x narration_wpm -- see this module's own
    # comment on WORDS_PER_CLAIM and generate_script's docstring above.
    # episode_target_minutes is accepted but unused here now.
    total_words = round(len(rows) * WORDS_PER_CLAIM)
    budgeted_word_counts = SectionWordCounts(
        cold_open=round(total_words * COLD_OPEN_SHARE),
        thesis=round(total_words * THESIS_SHARE),
        ground=round(total_words * GROUND_SHARE),
        sequence=round(total_words * SEQUENCE_SHARE),
        resolution=round(total_words * RESOLUTION_SHARE),
        return_=round(total_words * RETURN_SHARE),
    )
    # A report, not an input -- see SectionedScript.derived_runtime_minutes's
    # own docstring. Unrounded on purpose; nothing downstream enforces it.
    derived_runtime_minutes = total_words / profile.narration_wpm

    # Per-claim word_target against each section's own budget above --
    # uniform per claim, not split by thesis_bearing (see
    # _apply_word_targets' own docstring for why the split was removed,
    # not demoted). This is what the composed prompt sends as each
    # claim's own word_target (gemini_composition_provider.py), not just
    # a section-level number the model had to divide up itself. Return
    # is excluded on purpose: it never gets a claim list (see
    # chronological_composition.py), only the section budget itself.
    ground_claims = _apply_word_targets(ground_claims, budgeted_word_counts.ground)
    resolution_claims = _apply_word_targets(resolution_claims, budgeted_word_counts.resolution)
    sequence_claims = _apply_word_targets(sequence_claims, budgeted_word_counts.sequence)
    # cold_open_claim is the same claim as sequence_claims' cold-open
    # entry (rule 2: appears in exactly Cold Open and Sequence) -- pull
    # the word-targeted version back out so the two agree, even though
    # Cold Open itself is never sent to the provider (it reuses the raw
    # statement, see above) and never reads this value.
    cold_open_claim_output = next(
        c for c in sequence_claims if c.claim_id == cold_open_composable.claim_id
    )

    actual_word_counts = SectionWordCounts(
        cold_open=word_count(cold_open_text),
        thesis=word_count(thesis),
        ground=word_count(ground_text),
        sequence=word_count(sequence_text),
        resolution=word_count(resolution_text),
        return_=word_count(return_text),
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
        derived_runtime_minutes=derived_runtime_minutes,
        untagged_claim_count=untagged_claim_count,
        cold_open_claim=cold_open_claim_output,
        ground_claims=ground_claims,
        sequence_claims=sequence_claims,
        resolution_claims=resolution_claims,
    )


def _as_sentence(statement: str) -> str:
    text = statement.strip()
    if not text.endswith((".", "!", "?")):
        text += "."
    return text


def _to_claim_for_composition(claim: Claim, episode_claim: EpisodeClaim) -> ClaimForComposition:
    assert claim.id is not None
    return ClaimForComposition(
        claim_id=claim.id,
        statement=claim.statement,
        claim_type=claim.claim_type.value,
        confidence=claim.confidence.value,
        date_anchor=claim.date_anchor,
        thesis_bearing=episode_claim.thesis_bearing,
        # Placeholder -- every claim built here lands in exactly one of
        # ground_claims/sequence_claims/resolution_claims below, and all
        # three get their real word_target filled in by
        # _apply_word_targets() once that section's own budget is known.
        # No claim built by this function is returned with this value
        # still on it.
        word_target=0,
    )


def _apply_word_targets(
    claims: list[ClaimForComposition], section_budget: int
) -> list[ClaimForComposition]:
    """Every claim in the section gets the same word_target:
    round(section_budget / len(claims)). No thesis_bearing branching --
    this was a 60/40 split (docs/ARCHITECTURES.md sec 3.4 as originally
    written; briefly 45/55, one real scale run, no measured improvement)
    and is now removed, not demoted to a smaller gap. At the corrected
    per-claim rate (WORDS_PER_CLAIM=18, itself a correction of an
    earlier, asserted-not-measured 28), 60/40 stops being a defensible
    split rather than just an ineffective one: on the real 40-claim
    fixture, Sequence's non-thesis-bearing claims would get ~8 words
    each -- below the length of the claim statement itself (the
    shortest claim in that fixture is 7 words, most run 15-27). The
    split only ever looked harmless because it was dividing an inflated
    total (WORDS_PER_CLAIM=28, before that a target derived from
    episode_target_minutes); at an honest rate there's no room in it to
    give anyone less than everyone else without truncating them below
    their own source claim.

    word_target still exists and is still sent to the model per claim
    (gemini_composition_provider.py) -- per docs/HANDOFF.md sec 11 it
    grounds local sentence length, not the uniqueness mechanism. That
    mechanism is claim selection: which claims a human marked
    thesis-bearing decides which claims are even in an episode's pool
    (rule 6), not how many words the prose spends on each one once it's
    there. thesis_bearing is still passed to the model in the claims
    block for tone, even though it no longer changes word_target.

    Each claim's share is rounded to the nearest integer independently;
    rounding drift against the section total is not reconciled here --
    SectionWordCounts already reports the section-level total against
    rule 4, this is a breakdown of it, not a second total competing
    with it."""
    if not claims:
        return claims

    target = round(section_budget / len(claims))
    return [replace(c, word_target=target) for c in claims]
