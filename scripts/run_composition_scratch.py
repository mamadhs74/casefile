"""One-off script: run `compose_episode` against the real Gemini API for the
first time. `gemini_composition_provider.py` has never been executed --
docs/HANDOFF.md sec 7 finding #30.

Builds a synthetic episode in a temporary, file-based SQLite database --
NOT data/casefile.db -- using the same factories tests/test_chronological_
composition.py's own fixture-building code uses. Nothing here touches a
real subject or spends any research quota; the only real cost is the
Gemini composition calls themselves.

UPDATED to target subject 10 (docs/HANDOFF.md finding #43): CLAIM_SPECS
below is no longer the original fictional Ashgrove Mill set -- it's the
real 11 claims (ids 91-101) of subject 10's Paramount-Warner Bros. merger
story, copied verbatim (statement, date_anchor, section) from
data/casefile.db (read-only, nothing there is written to). THESIS and the
thesis-bearing selection are a human decision made for this run, not
inferred -- see the task this was built under. Claim set: 11 claims, 7
thesis-bearing (within rule 6's 5-10 band), 1 GROUND (91), 6 RESOLUTION
(93/95/96/98/99/101), 4 untagged (Sequence: 92/94/97/100) -- exercises all
4 possible calls (Ground, Sequence, Resolution, Return). rule 7's real
floor of 40 is not the point of this run, so min_claim_count is overridden
to 11 -- see docs/ARCHITECTURES.md sec 2 on why 40 is a placeholder anyway.

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
    "Paramount's takeover of Warner Bros. cleared regulators across "
    "multiple continents, but a last coalition lawsuit means the deal "
    "isn't final yet."
)

# (real_claim_id, statement, date_anchor, section, thesis_bearing) --
# subject 10, claims 91-101, the Paramount-Warner Bros. merger story
# (docs/HANDOFF.md finding #43). statement/date_anchor/section copied
# verbatim from data/casefile.db; date_anchor is None for all 11 (nothing
# in this story has one), so _sort_key's fallback to claim_id order is
# what actually orders Sequence here, and that order already matches the
# source article's own presentation order. real_claim_id is kept only for
# picking the cold-open claim below -- the scratch DB assigns its own ids.
CLAIM_SPECS: list[tuple[int, str, str | None, Section | None, bool]] = [
    (
        91,
        "Paramount is nearing completion of an $111 billion takeover of Warner Bros.",
        None,
        Section.GROUND,
        True,
    ),
    (
        92,
        "The Financial Times reported that the European Commission is expected to "
        "approve the Paramount-Warner Bros. merger with a condition that Paramount "
        "exit its joint venture with Universal Pictures.",
        None,
        None,
        False,
    ),
    (
        93,
        "Securities filings showed that competition regulators in China and South "
        "Africa cleared the Paramount-Warner Bros. merger.",
        None,
        Section.RESOLUTION,
        True,
    ),
    (
        94,
        "A Paramount spokesperson stated that the company has engaged constructively "
        "and transparently with all regulatory and law enforcement bodies.",
        None,
        None,
        False,
    ),
    (
        95,
        "Antitrust regulators in Saudi Arabia, Ukraine, Serbia, and North Macedonia "
        "found that the merger does not violate antitrust laws.",
        None,
        Section.RESOLUTION,
        True,
    ),
    (
        96,
        "Foreign investment regulators across multiple countries including Germany, "
        "France, and Spain have approved the merger.",
        None,
        Section.RESOLUTION,
        True,
    ),
    (
        97,
        "Paramount legal chief Makan Delrahim posted that regulators understand the "
        "transaction is procompetitive against tech monopolies.",
        None,
        None,
        False,
    ),
    (
        98,
        "The Justice Department's Antitrust Division signed off on the merger after "
        "determining it will increase competition across the media and entertainment "
        "ecosystem without requiring remedies or concessions.",
        None,
        Section.RESOLUTION,
        True,
    ),
    (
        99,
        "The Justice Department found that theatrical, linear TV, and streaming "
        "markets would not be harmed and required no divestitures or behavioral "
        "remedies.",
        None,
        Section.RESOLUTION,
        True,
    ),
    (
        100,
        "The Wall Street Journal reported that Larry Ellison donated approximately "
        "$45 million to a political nonprofit backing Trump's 2024 election.",
        None,
        None,
        False,
    ),
    (
        101,
        "A state coalition led by California is preparing a lawsuit expected within "
        "a month to challenge and block the merger.",
        None,
        Section.RESOLUTION,
        True,
    ),
]

# real subject-10 claim id chosen as cold open -- the still-open lawsuit,
# not a verdict or outcome (docs/ARCHITECTURES.md sec 3.1's own rule),
# and the claim the thesis's "but ... isn't final yet" clause turns on.
COLD_OPEN_REAL_CLAIM_ID = 101


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
            slug="scratch-subject10-paramount-wb-merger",
            title="SCRATCH TEST -- subject 10's real claims 91-101 (Paramount-WB merger)",
        ),
    )
    # real source_id=13 (hollywoodreporter.com) is CONTEMPORANEOUS, not
    # PRIMARY_RECORD -- kept accurate to the real source's tier rather than
    # silently upgrading it.
    source_id = _persist(session, make_source(subject_id, tier=SourceTier.CONTEMPORANEOUS))
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

    claim_ids_by_real_id: dict[int, int] = {}
    for real_claim_id, statement, date_anchor, section, thesis_bearing in CLAIM_SPECS:
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
        claim_ids_by_real_id[real_claim_id] = claim_id

    cold_open_claim_id = claim_ids_by_real_id[COLD_OPEN_REAL_CLAIM_ID]
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
            f"cold_open_claim_id={cold_open_claim_id}, 11 claims, min_claim_count=11\n"
        )

        provider = GeminiCompositionProvider(api_key)

        try:
            script = await compose_episode(session, episode_id, provider, min_claim_count=11)
        except Exception as exc:  # noqa: BLE001  -- report and stop, no retry, see module docstring
            print(f"composition failed, stopping (no retry): {exc!r}", file=sys.stderr)
            exit_code = 1
        else:
            _report(script)

    engine.dispose()
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
