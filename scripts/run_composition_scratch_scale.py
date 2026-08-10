"""Second scratch run: compose_episode against real Gemini at a realistic
claim count, after fixing the per-claim word_target bug found by
scripts/run_composition_scratch.py's first run -- see composition_provider.py
and chronological.py for the fix, gemini_composition_provider.py for the
prompt change.

Same temp-DB pattern as scripts/run_composition_scratch.py -- a
throwaway, file-based SQLite database, NOT data/casefile.db. Nothing here
touches a real subject or research quota; the only real cost is the
Gemini composition calls.

Claim set: 40 claims total (clears rule 7's real floor honestly, no
min_claim_count override), 8 thesis-bearing (rule 6's midpoint):
  - Ground: 5 claims, 1 thesis-bearing.
  - Sequence: 30 claims, 6 thesis-bearing.
  - Resolution: 5 claims, 1 thesis-bearing.
7 claims are CONTEMPORANEOUS_REPORT/REPORTED (attributed testimony or
period press), spread across all three sections; 2 more are
FACT/CONTESTED (conflicting accounts), both in Sequence -- 9 claims
total below ESTABLISHED confidence. Entirely synthetic, not a real case
-- continues the same fictional Ashgrove Mill fixture as the first
script, expanded to realistic scale.

Cold open: the claim where Pruitt finds the strongbox open -- a concrete
physical scene, not the verdict or outcome, per docs/ARCHITECTURES.md
sec 3.1.

Reports full composed text per section plus a per-claim word-target vs.
actual-words table. "Actual words devoted to it" is not something the
provider returns structurally -- ComposedSection carries only the raw
prose (see composition_provider.py's own docstring on why composed
prose has no equivalent of claim_extraction.py's locatable quoted_span).
The table below allocates the composed text back to claims by an
order-preserving heuristic (each claim gets a share of the section's
sentences proportional to its own word_target, consumed in the order the
prompt guarantees claims are not reordered in) -- an approximation, not
a code-verified or model-reported measurement. Flagged again in the
script's own output, not just here.

No retry of the whole run is built into this script -- a provider
failure on any section stops the script and reports the error. This
does not disable GeminiCompositionProvider's own per-call truncation
retry (existing, already-approved behavior); unlikely to trigger at
these section budgets.

Usage:
    uv run python -m scripts.run_composition_scratch_scale
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.genai.errors import ServerError
from sqlmodel import Session, SQLModel, create_engine

import packages.db.listeners  # noqa: F401  registers narratable/eligibility listeners
import packages.db.models  # noqa: F401  registers tables on SQLModel.metadata
from packages.db.models import Claim, Episode, TimestampedModel
from packages.domain.enums import (
    ClaimConfidence,
    ClaimType,
    EpisodeArchitecture,
    Section,
    SourceTier,
)
from packages.script.chronological import SectionedScript
from packages.script.chronological_composition import compose_episode
from packages.script.composition import word_count
from packages.script.composition_provider import (
    ClaimForComposition,
    ComposedSection,
    CompositionProvider,
)
from packages.script.gemini_composition_provider import GeminiCompositionProvider
from tests.factories import (
    make_claim,
    make_claim_source,
    make_episode,
    make_episode_claim,
    make_source,
    make_strategy,
    make_subject,
    make_subtitle_style,
    make_variation_profile,
)

# Change A: half of chronological.py's real EPISODE_TARGET_MINUTES
# default (20), passed as generate_script's/compose_episode's own
# episode_target_minutes override -- see chronological.py's docstring
# for why this is an injectable per-call parameter rather than a change
# to the module constant itself. At this fixture's narration_wpm (145,
# tests/factories.py::make_variation_profile's default), 10 minutes is
# ~1,450 words -- the per-section share constants are untouched, only
# this total moves.
EPISODE_TARGET_MINUTES_OVERRIDE = 10

THESIS = (
    "The Ashgrove Mill theft was solved not by the missing money but by "
    "one witness's willingness to name a supervisor."
)

# make_claim (tests/factories.py) stores these straight onto the Claim
# model and chronological.py later calls .value on them -- these must be
# the real enum members, not their .value strings.
FACT = ClaimType.FACT
REPORT = ClaimType.CONTEMPORANEOUS_REPORT
ESTABLISHED = ClaimConfidence.ESTABLISHED
REPORTED = ClaimConfidence.REPORTED
CONTESTED = ClaimConfidence.CONTESTED

# (statement, date_anchor, section, thesis_bearing, claim_type, confidence)
# All entirely synthetic -- continues scripts/run_composition_scratch.py's
# fictional Ashgrove Mill case at realistic scale.
GROUND_SPECS: list[tuple[str, str | None, Section | None, bool, ClaimType, ClaimConfidence]] = [
    (
        "Cole Pruitt had served as the mill's overnight watchman since 1908.",
        None,
        Section.GROUND,
        True,
        FACT,
        ESTABLISHED,
    ),
    (
        "Ashgrove Mill employed around 40 workers and processed cotton for "
        "regional distributors.",
        None,
        Section.GROUND,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "The mill's payroll was kept in a single iron strongbox behind the "
        "foreman's desk in the counting house.",
        None,
        Section.GROUND,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Alden Reyes had worked as floor foreman at Ashgrove Mill for six "
        "years by the winter of 1911.",
        None,
        Section.GROUND,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "A regional trade paper described Ashgrove Mill in 1910 as one of "
        "the county's most modern cotton works.",
        "1910",
        Section.GROUND,
        False,
        REPORT,
        REPORTED,
    ),
]

SEQUENCE_SPECS: list[tuple[str, str | None, Section | None, bool, ClaimType, ClaimConfidence]] = [
    (
        "Reyes requested an advance against his wages from Kell's "
        "bookkeeper, which was refused.",
        "1911-03-01",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Pruitt found the counting-house door unlocked and the strongbox "
        "open at the start of his shift.",
        "1911-03-02",
        None,
        True,
        FACT,
        ESTABLISHED,
    ),
    (
        "Sheriff Dunmore was summoned to the mill within the hour and "
        "found no signs of forced entry on the counting-house door.",
        "1911-03-02",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        'A local paper reported the theft under the headline "Daring '
        'Robbery at Ashgrove Mill," describing the loss as the largest '
        "in the county's memory.",
        "1911-03-03",
        None,
        False,
        REPORT,
        REPORTED,
    ),
    (
        "Ledger clerk Edith Voss told investigators she saw Reyes in the "
        "counting house after hours carrying a canvas satchel.",
        "1911-03-04",
        None,
        True,
        REPORT,
        REPORTED,
    ),
    (
        "Kell's bookkeeper confirmed the payroll had been counted and "
        "locked in the strongbox at six that evening, per the mill's "
        "standing procedure.",
        "1911-03-04",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "The strongbox held $4,180 in mill payroll the previous evening "
        "and was empty when Pruitt found it.",
        "1911-03-05",
        None,
        True,
        FACT,
        ESTABLISHED,
    ),
    (
        "Kell offered a $200 reward for information leading to a "
        "conviction.",
        "1911-03-05",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Sheriff Dunmore questioned six mill employees who held keys to "
        "the counting house.",
        "1911-03-06",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Accounts differ on whether Reyes carried his own key to the "
        "strongbox: Sheriff Dunmore's report says he did not, while clerk "
        "Thomas Farrow recalled that he did.",
        "1911-03-06",
        None,
        False,
        FACT,
        CONTESTED,
    ),
    (
        "Kell hired Pinkerton agent Silas Marrow to assist the "
        "investigation.",
        "1911-03-07",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Marrow obtained bank records for every mill employee with "
        "counting-house access.",
        "1911-03-08",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Marrow traced $2,900 of the missing payroll to a bank deposit "
        "under Reyes's name in Calloway County.",
        "1911-03-09",
        None,
        True,
        FACT,
        ESTABLISHED,
    ),
    (
        "Reyes was arrested that afternoon at his boarding house.",
        "1911-03-09",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "The arresting deputies reported that Reyes made no statement at "
        "the time of his arrest.",
        "1911-03-09",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        'A neighboring county paper carried the arrest under the headline '
        '"Mill Foreman Held in Payroll Theft."',
        "1911-03-10",
        None,
        False,
        REPORT,
        REPORTED,
    ),
    (
        "Defense attorney Wallace Prine was retained by Reyes's family.",
        "1911-03-11",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Reyes's landlady testified she believed he had been at the "
        "boarding house through the night of March 4th, contradicting "
        "Voss's account.",
        "1911-03-12",
        None,
        False,
        REPORT,
        CONTESTED,
    ),
    (
        "Voss repeated her account of the after-hours sighting before a "
        "grand jury.",
        "1911-03-13",
        None,
        True,
        REPORT,
        REPORTED,
    ),
    (
        "The grand jury returned an indictment against Reyes for grand "
        "larceny.",
        "1911-03-14",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Prine argued in a pretrial motion that the bank deposit could "
        "reflect Reyes's own savings rather than stolen funds.",
        "1911-03-15",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Marrow testified that Reyes's own bank balance before March 5th "
        "had never exceeded $80.",
        "1911-03-16",
        None,
        True,
        FACT,
        ESTABLISHED,
    ),
    (
        "Mill delivery driver Otis Bramwell testified he saw Reyes near "
        "the rail depot on the morning of March 9th carrying a heavy "
        "carpet bag.",
        "1911-03-17",
        None,
        False,
        REPORT,
        REPORTED,
    ),
    (
        "The trial opened before Judge Harlan Voss in the county "
        "courthouse.",
        "1911-03-18",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "The prosecution called five witnesses over two days, including "
        "Voss, Marrow, and Bramwell.",
        "1911-03-19",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "Prine called two character witnesses on Reyes's behalf.",
        "1911-03-19",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "The defense's closing argument emphasized that no witness saw "
        "Reyes physically remove money from the strongbox.",
        "1911-03-19",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "The prosecution's closing argument centered on Voss's testimony "
        "and the traced bank deposit as the case's two strongest points.",
        "1911-03-20",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "The jury deliberated for three hours before returning its "
        "verdict.",
        "1911-03-20",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "The jury convicted Reyes of grand larceny.",
        "1911-03-20",
        None,
        False,
        FACT,
        ESTABLISHED,
    ),
]

RESOLUTION_SPECS: list[tuple[str, str | None, Section | None, bool, ClaimType, ClaimConfidence]] = [
    (
        "The indictment record credits Voss's testimony, not the traced "
        "bank deposit, as the piece of evidence the grand jury cited "
        "first.",
        "1911-03-14",
        Section.RESOLUTION,
        True,
        FACT,
        ESTABLISHED,
    ),
    (
        "Judge Harlan Voss sentenced Reyes to four years at the state "
        "penitentiary on March 21, 1911.",
        "1911-03-21",
        Section.RESOLUTION,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        "The remaining $1,280 of the missing payroll was never "
        "recovered.",
        None,
        Section.RESOLUTION,
        False,
        FACT,
        ESTABLISHED,
    ),
    (
        'A regional paper reported the sentencing under the headline '
        '"Mill Foreman Gets Four Years," noting the unrecovered balance.',
        "1911-03-22",
        Section.RESOLUTION,
        False,
        REPORT,
        REPORTED,
    ),
    (
        "Kell installed a second strongbox lock at Ashgrove Mill within a "
        "month of the sentencing, requiring two employees to open it "
        "together.",
        "1911-04-01",
        Section.RESOLUTION,
        False,
        FACT,
        ESTABLISHED,
    ),
]

ALL_SPECS = GROUND_SPECS + SEQUENCE_SPECS + RESOLUTION_SPECS
COLD_OPEN_STATEMENT = (
    "Pruitt found the counting-house door unlocked and the strongbox open "
    "at the start of his shift."
)


def _persist[T: TimestampedModel](session: Session, obj: T) -> int:
    session.add(obj)
    session.commit()
    session.refresh(obj)
    assert obj.id is not None
    return obj.id


def _build_episode(session: Session, strategy_id: int) -> tuple[int, int]:
    subject_id = _persist(
        session,
        make_subject(
            strategy_id,
            slug="scratch-ashgrove-mill-scale",
            title="SCRATCH TEST -- Ashgrove Mill at scale (synthetic, not a real case)",
        ),
    )
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.PRIMARY_RECORD))
    subtitle_style_id = _persist(session, make_subtitle_style())
    variation_profile_id = _persist(
        session, make_variation_profile(strategy_id, subtitle_style_id)
    )
    episode_id = _persist(
        session,
        make_episode(
            subject_id,
            variation_profile_id,
            thesis=THESIS,
            architecture=EpisodeArchitecture.CHRONOLOGICAL,
        ),
    )

    cold_open_claim_id: int | None = None
    for statement, date_anchor, section, thesis_bearing, claim_type, confidence in ALL_SPECS:
        claim_id = _persist(
            session,
            make_claim(
                subject_id,
                statement=statement,
                date_anchor=date_anchor,
                section=section,
                claim_type=claim_type,
                confidence=confidence,
            ),
        )
        session.add(make_claim_source(claim_id, source_id))
        session.commit()

        claim = session.get(Claim, claim_id)
        assert claim is not None
        claim.narratable = True
        session.add(claim)
        session.commit()

        session.add(make_episode_claim(episode_id, claim_id, thesis_bearing=thesis_bearing))
        session.commit()

        if statement == COLD_OPEN_STATEMENT:
            cold_open_claim_id = claim_id

    assert cold_open_claim_id is not None
    episode = session.get(Episode, episode_id)
    assert episode is not None
    episode.cold_open_claim_id = cold_open_claim_id
    session.add(episode)
    session.commit()

    return episode_id, cold_open_claim_id


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _attribute_words_to_claims(
    text: str, claims: list[ClaimForComposition]
) -> dict[int, int]:
    """Heuristic only -- see module docstring. Splits composed text into
    sentences, then walks claims in the given (guaranteed-preserved)
    order, greedily consuming a number of sentences proportional to each
    claim's own share of the total word_target. Not a structural
    guarantee: a claim could be elaborated across a different number of
    sentences than its word_target share predicts, especially when the
    model runs two claims together in one sentence. Any leftover
    sentences (rounding, or the model writing more/fewer sentences than
    predicted) are appended to the last claim rather than dropped."""
    if not claims:
        return {}
    sentences = [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]
    if not sentences:
        return {c.claim_id: 0 for c in claims}

    total_target = sum(c.word_target for c in claims) or len(claims)
    result: dict[int, int] = {}
    cursor = 0
    for i, c in enumerate(claims):
        if i == len(claims) - 1:
            share = sentences[cursor:]
        else:
            n = max(1, round(len(sentences) * c.word_target / total_target))
            n = min(n, len(sentences) - cursor - (len(claims) - i - 1))
            n = max(n, 0)
            share = sentences[cursor : cursor + n]
            cursor += n
        result[c.claim_id] = sum(len(s.split()) for s in share)
    return result


def _print_claim_table(name: str, claims: list[ClaimForComposition], composed_text: str) -> None:
    actuals = _attribute_words_to_claims(composed_text, claims)
    print(f"--- {name} claims: word_target vs. heuristic actual words ---")
    print(f"{'claim_id':>8}  {'thesis':>6}  {'target':>6}  {'actual~':>7}  statement")
    for c in claims:
        actual = actuals.get(c.claim_id, 0)
        print(
            f"{c.claim_id:>8}  {str(c.thesis_bearing):>6}  {c.word_target:>6}  "
            f"{actual:>7}  {c.statement[:70]}"
        )
    thesis_claims = [c for c in claims if c.thesis_bearing]
    rest_claims = [c for c in claims if not c.thesis_bearing]
    if thesis_claims and rest_claims:
        avg_thesis = sum(actuals.get(c.claim_id, 0) for c in thesis_claims) / len(thesis_claims)
        avg_rest = sum(actuals.get(c.claim_id, 0) for c in rest_claims) / len(rest_claims)
        ratio = avg_thesis / avg_rest if avg_rest else float("inf")
        print(
            f"avg actual~ words: thesis-bearing={avg_thesis:.1f}, "
            f"rest={avg_rest:.1f}, ratio={ratio:.2f}x"
        )
    print()


# Crude on purpose (Change D) -- not a real content-word extractor, just
# enough to catch "restated the same fact in different words" the way a
# human skimming for it would: strip common function words, compare
# what's left. False positives (two sentences that legitimately share
# three names) are expected and fine to eyeball; false negatives (a
# genuine restatement using entirely different vocabulary) are the real
# limitation and not something this check can catch.
_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    """
    the a an of to and in on at for with by from as is was were are be
    been being that this these those which who whom his her their its
    it he she they we you i not no than then so but or if into out up
    down over under after before during between within without about
    across around near far more most less least very just also only
    even still yet already now here there when where why how what had
    has have did do does would could should will shall may might s t
    """.split()
)


def _content_words(sentence: str) -> set[str]:
    words = _WORD_RE.findall(sentence.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _check_repetition(section_name: str, text: str) -> bool:
    """Prints any two sentences in text sharing >=3 content words.
    Returns whether anything was found, so callers can decide what to do
    with a clean section. Not scoped to which claim a sentence came
    from -- it doesn't need to be, restating a fact is the defect
    regardless of whether it happens within one claim's passage or
    across two."""
    sentences = [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]
    tagged = [(s, _content_words(s)) for s in sentences]
    found = False
    print(f"--- {section_name} repetition check (>=3 shared content words) ---")
    for i in range(len(tagged)):
        for j in range(i + 1, len(tagged)):
            shared = tagged[i][1] & tagged[j][1]
            if len(shared) >= 3:
                found = True
                print(f"  [{i}] <-> [{j}]  shared={sorted(shared)}")
                print(f"    [{i}] {tagged[i][0]}")
                print(f"    [{j}] {tagged[j][0]}")
    if not found:
        print("  none found")
    print()
    return found


def _report(script: SectionedScript) -> None:
    sections: list[tuple[str, str, int, int]] = [
        (
            "Cold Open",
            script.cold_open,
            script.actual_word_counts.cold_open,
            script.budgeted_word_counts.cold_open,
        ),
        (
            "Thesis",
            script.thesis,
            script.actual_word_counts.thesis,
            script.budgeted_word_counts.thesis,
        ),
        (
            "Ground",
            script.ground,
            script.actual_word_counts.ground,
            script.budgeted_word_counts.ground,
        ),
        (
            "Sequence",
            script.sequence,
            script.actual_word_counts.sequence,
            script.budgeted_word_counts.sequence,
        ),
        (
            "Resolution",
            script.resolution,
            script.actual_word_counts.resolution,
            script.budgeted_word_counts.resolution,
        ),
        (
            "Return",
            script.return_,
            script.actual_word_counts.return_,
            script.budgeted_word_counts.return_,
        ),
    ]
    for section_name, text, actual, budget in sections:
        pct = (actual / budget * 100) if budget else 0.0
        print(
            f"=== {section_name} -- {actual} words actual / "
            f"{budget} words budgeted ({pct:.0f}%) ==="
        )
        print(text if text else "(empty)")
        print()

    print(
        "=== per-claim table (heuristic actual-word attribution -- see "
        "module docstring) ===\n"
    )
    _print_claim_table("Ground", script.ground_claims, script.ground)
    _print_claim_table("Sequence", script.sequence_claims, script.sequence)
    _print_claim_table("Resolution", script.resolution_claims, script.resolution)

    print("=== repetition check, replayed against final (correctly-labeled) text ===\n")
    _check_repetition("Ground", script.ground)
    _check_repetition("Sequence", script.sequence)
    _check_repetition("Resolution", script.resolution)
    _check_repetition("Return", script.return_)


# chronological_composition.py::compose_episode's own call order (not
# changed here, just relied on): Sequence always, Return always (empty
# claims), then Ground and Resolution each only if generate_script put a
# claim in them. This fixture has both non-empty, so all four calls
# happen in exactly this order -- that's what makes labeling by index
# safe here; it is not a general-purpose section-name inference.
_CALL_ORDER_LABELS = ("Sequence", "Return", "Ground", "Resolution")


class _LoggingCompositionProvider:
    """Wraps a real CompositionProvider and prints each section's label,
    composed text, and word count immediately as that call returns --
    before compose_episode moves on to the next section. Delegates every
    call unchanged; does not touch GeminiCompositionProvider or
    compose_episode. Exists because a failure on a later call (e.g.
    Ground, the 3rd) would otherwise discard whatever Sequence and
    Return already produced -- quota spent on them, nothing read."""

    def __init__(self, inner: CompositionProvider) -> None:
        self._inner = inner
        self._call_index = 0

    async def compose_section(
        self, claims: list[ClaimForComposition], thesis: str, word_budget: int
    ) -> ComposedSection:
        label = (
            _CALL_ORDER_LABELS[self._call_index]
            if self._call_index < len(_CALL_ORDER_LABELS)
            else f"call {self._call_index + 1}"
        )
        self._call_index += 1
        result = await self._inner.compose_section(claims, thesis, word_budget)
        actual = word_count(result.text)
        print(f"[live] {label} returned -- {actual} words / {word_budget} budgeted")
        print(result.text)
        print()
        _check_repetition(label, result.text)  # Change D
        return result


MAX_ATTEMPTS = 3  # 1 initial + up to 2 retries, 503 UNAVAILABLE only
RETRY_DELAY_SECONDS = 60


async def _compose_with_503_retry(
    session: Session,
    episode_id: int,
    inner_provider: CompositionProvider,
    *,
    episode_target_minutes: int,
) -> SectionedScript:
    """Retries the whole compose_episode call, up to MAX_ATTEMPTS total,
    only when the failure is ServerError with code 503 (transient
    overload) -- any other error, including a ServerError with a
    different code, propagates immediately, no retry. A retry re-runs
    every call from Sequence, including ones that already succeeded --
    _LoggingCompositionProvider's live printing is what keeps that
    output from being silently lost if a later attempt fails too.

    A fresh _LoggingCompositionProvider is built per attempt, wrapping
    the same inner_provider each time -- found the hard way on this
    function's first real run: passing one shared _LoggingCompositionProvider
    across attempts let its _call_index carry over from a failed
    attempt's partial progress, so a later attempt's real Sequence call
    printed under whatever label the index had drifted to (e.g. "Ground"
    or "Resolution") instead of "Sequence". The composed text itself was
    still correct -- only the printed label was wrong, recoverable
    afterward by matching each block's word_budget back to
    SectionWordCounts, since every section's budget is distinct. Fixed
    at the source instead: each attempt gets index 0."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        provider = _LoggingCompositionProvider(inner_provider)
        try:
            return await compose_episode(
                session,
                episode_id,
                provider,
                episode_target_minutes=episode_target_minutes,
            )
        except ServerError as exc:
            if exc.code != 503 or attempt == MAX_ATTEMPTS:
                raise
            print(
                f"attempt {attempt}/{MAX_ATTEMPTS} hit 503 UNAVAILABLE -- "
                f"waiting {RETRY_DELAY_SECONDS}s before retrying...",
                file=sys.stderr,
            )
            await asyncio.sleep(RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")  # loop always returns or raises


async def main() -> int:
    load_dotenv()  # .env is not loaded automatically anywhere else yet

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    db_path = Path("/tmp/casefile_composition_scratch_scale.db")
    if db_path.exists():
        db_path.unlink()
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    print(f"scratch database (temporary, not data/casefile.db): {db_path}")

    exit_code = 0
    with Session(engine) as session:
        strategy = make_strategy()
        session.add(strategy)
        session.commit()
        session.refresh(strategy)
        assert strategy.id is not None

        episode_id, cold_open_claim_id = _build_episode(session, strategy.id)
        print(
            f"built scratch episode_id={episode_id}, "
            f"cold_open_claim_id={cold_open_claim_id}, "
            f"{len(ALL_SPECS)} claims, min_claim_count unchanged (real floor of 40), "
            f"episode_target_minutes={EPISODE_TARGET_MINUTES_OVERRIDE} "
            f"(~{EPISODE_TARGET_MINUTES_OVERRIDE * 145} words at 145 wpm)\n"
        )

        inner_provider = GeminiCompositionProvider(api_key)

        try:
            script = await _compose_with_503_retry(
                session,
                episode_id,
                inner_provider,
                episode_target_minutes=EPISODE_TARGET_MINUTES_OVERRIDE,
            )
        except ServerError as exc:
            print(
                f"composition failed after {MAX_ATTEMPTS} attempts, all 503 "
                f"UNAVAILABLE -- stopping, holding until tomorrow: {exc!r}",
                file=sys.stderr,
            )
            exit_code = 1
        except Exception as exc:  # noqa: BLE001  -- any non-503 error: stop, no retry
            print(f"composition failed, stopping (no retry): {exc!r}", file=sys.stderr)
            exit_code = 1
        else:
            _report(script)

    engine.dispose()
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
