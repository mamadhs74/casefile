"""Compose real Borden claims into prose with real Gemini (one call),
then narrate, render, and mux the result -- the first real test of a
composed (not claim-driven) card sequence.

QUOTA: exactly ONE Gemini call. Gemini free tier is 20 requests/day,
shared across every script and experiment that uses it -- no retry
loop, no second call to compare, no verification call. If the call
fails, this prints the error and exits; it does not retry.

SCOPE: read-only database access. SELECT only -- same read-only URI
mode as scripts/render_scratch_visual.py (confirmed there, empirically,
to raise on a write attempt, not just documented as read-only). No
schema change.

Subject 8's date_anchor LIKE '1893%' filter is the same deliberate,
non-negotiable boundary scripts/render_scratch_visual.py's own
docstring explains at length: it isolates the real Lizzie Borden
material (source_7) from the two unrelated cases sharing subject 8's
row. Not widened here either.

Composed prose has no per-claim provenance: once Gemini turns 22
claims into a handful of sentences, there is no longer a claim_id to
attribute any one sentence back to. packages/visual/planner.py's
claim-driven mapping (plan_cards) assumes exactly that provenance and
doesn't apply here, so this script builds its own PlannedCard sequence
directly -- one chapter_title card, then one StatementCardSpec card
per composed sentence, all with claim_id=None. This is a scratch-script
decision, not a change to planner.py; that module is untouched.

Narration, rendering, and muxing reuse scripts/render_scratch_visual.py's
own helpers directly (imported, not copied) -- KokoroProvider synthesis,
ffprobe duration measurement, and the concat/mux ffmpeg steps are
identical whether a card's text came from a claim statement or a
composed sentence.

Usage:
    uv run python -m scripts.compose_scratch_borden
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlmodel import Session, col, select

from packages.db.models import Claim
from packages.script.chronological import WORDS_PER_CLAIM
from packages.script.composition import compose_section_text
from packages.script.composition_provider import ClaimForComposition
from packages.script.gemini_composition_provider import GeminiCompositionProvider
from packages.visual.cards import ChapterTitleSpec, StatementCardSpec
from packages.visual.motion import assign_motion
from packages.visual.palette import palette_for
from packages.visual.planner import PlannedCard
from packages.visual.render import render_cards
from packages.visual.timing import total_runtime
from packages.voice.kokoro_provider import DEFAULT_VOICE_NAME
from scripts.render_scratch_visual import (
    _concat_audio,
    _format_mmss,
    _mux_narration,
    _probe_duration,
    _synthesize_narration,
)

DB_PATH = Path("data/casefile.db")
OUT_DIR = Path("data/renders/compose_scratch_borden")

# Deliberate, non-negotiable -- see module docstring and
# scripts/render_scratch_visual.py for the full reasoning.
SUBJECT_ID = 8
DATE_PREFIX = "1893"

ARCHITECTURE = "chronological"
CHAPTER_TITLE = "Fall River, 1893"

# Editable by hand between runs -- a module constant, not an argparse
# flag, because the point is to read the composed output and rewrite
# this, not script around it.
THESIS = (
    "The Borden case was decided less by physical evidence than by "
    "what the jury was willing to believe about a woman of her standing."
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_ENDS_WITH_INITIAL = re.compile(r"\b[A-Z]\.$")


def _fetch_claims_for_composition(session: Session) -> list[ClaimForComposition]:
    """claim_type/confidence stringified with .name, matching
    scripts/render_scratch_visual.py's own _fetch_claim_records.
    thesis_bearing=False for every claim -- per
    docs/ARCHITECTURES.md's own corrected reading (packages/visual's
    docs), thesis_bearing now governs claim *selection*, not word
    allocation, and this script selects its claims by date filter, not
    by a human thesis-bearing flag. word_target is WORDS_PER_CLAIM
    (18, measured) for every claim, uniform -- see module docstring on
    why the 60/40 split ClaimForComposition's own docstring still
    describes does not apply; that docstring is stale, not this call
    site."""
    query = (
        select(Claim)
        .where(
            Claim.subject_id == SUBJECT_ID,
            col(Claim.date_anchor).like(f"{DATE_PREFIX}%"),
        )
        .order_by(col(Claim.id))
    )
    claims = session.exec(query).all()

    records: list[ClaimForComposition] = []
    for claim in claims:
        assert claim.id is not None  # a queried, persisted row always has one
        records.append(
            ClaimForComposition(
                claim_id=claim.id,
                statement=claim.statement,
                claim_type=claim.claim_type.name,
                confidence=claim.confidence.name,
                date_anchor=claim.date_anchor,
                thesis_bearing=False,
                word_target=WORDS_PER_CLAIM,
            )
        )
    return records


def _split_sentences(text: str) -> list[str]:
    """Crude, not a real sentence tokenizer: splits on end-of-sentence
    punctuation followed by whitespace, then merges back any fragment
    that ends in a single capital letter and a period -- a middle
    initial ("Lizzie A.", "Hosea M."), not a real sentence boundary.
    Confirmed against this exact failure mode on real composed output
    before this merge step existed: without it, "Lizzie A. Borden was
    acquitted..." split into "Lizzie A." and "Borden was
    acquitted...", producing two cards -- one an unreadable fragment --
    for what is one sentence."""
    raw = [s for s in _SENTENCE_SPLIT.split(text.strip()) if s]

    merged: list[str] = []
    for fragment in raw:
        if merged and _ENDS_WITH_INITIAL.search(merged[-1]):
            merged[-1] = f"{merged[-1]} {fragment}"
        else:
            merged.append(fragment)
    return merged


def _build_cards(sentences: list[str]) -> list[PlannedCard]:
    cards: list[PlannedCard] = [
        PlannedCard(
            kind="chapter_title", claim_id=None, spec=ChapterTitleSpec(title=CHAPTER_TITLE)
        )
    ]
    for sentence in sentences:
        cards.append(
            PlannedCard(
                kind="statement", claim_id=None, spec=StatementCardSpec(statement=sentence)
            )
        )
    return cards


async def main() -> int:
    load_dotenv()  # .env is not loaded automatically anywhere else yet

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    engine = create_engine(f"sqlite:///file:{DB_PATH}?mode=ro&uri=true")
    with Session(engine) as session:
        claims = _fetch_claims_for_composition(session)

    print(
        f"claims pulled (subject_id={SUBJECT_ID}, "
        f"date_anchor LIKE '{DATE_PREFIX}%'): {len(claims)}"
    )

    word_budget = len(claims) * WORDS_PER_CLAIM
    print(f"word budget: {word_budget} ({len(claims)} claims x {WORDS_PER_CLAIM} words/claim)")

    provider = GeminiCompositionProvider(api_key)
    try:
        result = await compose_section_text(provider, claims, THESIS, word_budget)
    except Exception as exc:  # noqa: BLE001  -- report and stop, no retry, see module docstring
        print(f"composition failed, stopping (no retry): {exc!r}", file=sys.stderr)
        return 1

    print(f"actual word count: {result.actual_word_count}  budgeted: {result.budgeted_word_count}")
    print()
    print(result.text)
    print()

    sentences = _split_sentences(result.text)
    print(f"sentences: {len(sentences)}")

    cards = _build_cards(sentences)
    print(f"cards: {len(cards)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"synthesizing {len(cards)} clips (voice={DEFAULT_VOICE_NAME})...")
    synthesis_start = time.perf_counter()
    narration_paths = _synthesize_narration(cards, OUT_DIR, DEFAULT_VOICE_NAME)
    synthesis_elapsed = time.perf_counter() - synthesis_start
    print(
        f"synthesis wall-clock time: {synthesis_elapsed:.3f}s ({_format_mmss(synthesis_elapsed)})"
    )

    measured_durations = [_probe_duration(p) for p in narration_paths]
    measured_runtime = total_runtime(measured_durations)
    print(f"measured runtime: {measured_runtime:.3f}s ({_format_mmss(measured_runtime)})")

    motions = assign_motion(cards, ARCHITECTURE)
    # episode_id is unused by palette_for in v1 -- see that function's
    # own docstring. 0 is arbitrary; no real Episode exists here.
    palette = palette_for(ARCHITECTURE, episode_id=0)
    silent_video_path = render_cards(cards, palette, measured_durations, motions, OUT_DIR)

    narration_track_path = OUT_DIR / "narration.wav"
    _concat_audio(narration_paths, OUT_DIR / "narration_concat_list.txt", narration_track_path)

    final_path = OUT_DIR / "cards_narrated.mp4"
    _mux_narration(silent_video_path, narration_track_path, final_path)

    print(f"output: {final_path}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
