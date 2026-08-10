"""One-off script: run `compose_episode` against the real Gemini API for the
first time. `gemini_composition_provider.py` has never been executed --
docs/HANDOFF.md sec 7 finding #30.

Builds a synthetic episode in a temporary, file-based SQLite database --
NOT data/casefile.db -- using the same factories tests/test_chronological_
composition.py's own fixture-building code uses. Nothing here touches a
real subject or spends any research quota; the only real cost is the
Gemini composition calls themselves.

Claim set: 5 claims, all thesis-bearing (rule 6's floor of 5), one GROUND,
one RESOLUTION, three untagged (Sequence) -- the same shape as
tests/test_chronological_composition.py's ceiling case, so this exercises
all 4 possible calls (Ground, Sequence, Resolution, Return). rule 7's real
floor of 40 is not the point of this run, so min_claim_count is overridden
to 5 -- see docs/ARCHITECTURES.md sec 2 on why 40 is a placeholder anyway.

No retry of the whole run is built into this script on purpose -- a
provider failure on any section stops the script and reports the error,
rather than silently re-calling. Note this does not disable
GeminiCompositionProvider's own per-call truncation retry (one retry at a
higher max_output_tokens ceiling before it raises
TruncatedCompositionError) -- that is existing, already-approved provider
behavior, not something this script adds, and is very unlikely to trigger
at these section word budgets (under 2,000 words each).

Usage:
    uv run python -m scripts.run_composition_scratch
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, SQLModel, create_engine

import packages.db.listeners  # noqa: F401  registers narratable/eligibility listeners
import packages.db.models  # noqa: F401  registers tables on SQLModel.metadata
from packages.db.models import Claim, Episode, TimestampedModel
from packages.domain.enums import EpisodeArchitecture, Section, SourceTier
from packages.script.chronological import SectionedScript
from packages.script.chronological_composition import compose_episode
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

THESIS = (
    "The Ashgrove Mill theft was solved not by the missing money but by "
    "one witness's willingness to name a supervisor."
)

# (statement, date_anchor, section, thesis_bearing) -- entirely synthetic,
# not a real case. claim_ids[1] (the strongbox claim) is used as the cold
# open below: a concrete physical claim, not the verdict or outcome, per
# docs/ARCHITECTURES.md sec 3.1.
CLAIM_SPECS: list[tuple[str, str, Section | None, bool]] = [
    (
        "On the morning of March 2, 1911, the Ashgrove Mill's overnight "
        "watchman, Cole Pruitt, reported finding the counting-house door "
        "unlocked and the strongbox open.",
        "1911-03-02",
        Section.GROUND,
        True,
    ),
    (
        "The strongbox held $4,180 in mill payroll the previous evening "
        "and was empty when Pruitt found it.",
        "1911-03-05",
        None,
        True,
    ),
    (
        "Ledger clerk Edith Voss told investigators she had seen foreman "
        "Alden Reyes in the counting house after hours on March 4, "
        "carrying a canvas satchel.",
        "1911-03-06",
        None,
        True,
    ),
    (
        "Reyes was arrested on March 9 after a Pinkerton agent traced "
        "$2,900 of the missing payroll to a bank deposit under his name in "
        "a neighboring county.",
        "1911-03-10",
        None,
        True,
    ),
    (
        "A jury convicted Reyes of grand larceny on March 20, 1911; the "
        "remaining $1,280 was never recovered.",
        "1911-03-20",
        Section.RESOLUTION,
        True,
    ),
]


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
            slug="scratch-ashgrove-mill",
            title="SCRATCH TEST -- Ashgrove Mill (synthetic, not a real case)",
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

    claim_ids: list[int] = []
    for statement, date_anchor, section, thesis_bearing in CLAIM_SPECS:
        claim_id = _persist(
            session,
            make_claim(subject_id, statement=statement, date_anchor=date_anchor, section=section),
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
        claim_ids.append(claim_id)

    cold_open_claim_id = claim_ids[1]
    episode = session.get(Episode, episode_id)
    assert episode is not None
    episode.cold_open_claim_id = cold_open_claim_id
    session.add(episode)
    session.commit()

    return episode_id, cold_open_claim_id


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
    for name, text, actual, budget in sections:
        pct = (actual / budget * 100) if budget else 0.0
        print(f"=== {name} -- {actual} words actual / {budget} words budgeted ({pct:.0f}%) ===")
        print(text if text else "(empty)")
        print()


async def main() -> int:
    load_dotenv()  # .env is not loaded automatically anywhere else yet

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    db_path = Path("/tmp/casefile_composition_scratch.db")
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
            f"cold_open_claim_id={cold_open_claim_id}, 5 claims, min_claim_count=5\n"
        )

        provider = GeminiCompositionProvider(api_key)

        try:
            script = await compose_episode(session, episode_id, provider, min_claim_count=5)
        except Exception as exc:  # noqa: BLE001  -- report and stop, no retry, see module docstring
            print(f"composition failed, stopping (no retry): {exc!r}", file=sys.stderr)
            exit_code = 1
        else:
            _report(script)

    engine.dispose()
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
