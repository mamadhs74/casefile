"""Card durations from word counts.

These are estimates derived from word count and a fixed narration
rate, NOT measured from real audio. Nothing here has run through TTS
or forced alignment. A later task replaces this module's output with
real per-word timings from faster-whisper, once narration audio
actually exists to align against (docs/HANDOFF.md's stack notes) --
this module exists so the render pipeline downstream of it (motion,
shot sequencing) has *something* to schedule against before that task
is built, not because word-count timing is the intended final source
of truth.

SCOPE BOUNDARY, same posture as the rest of packages/visual: pure
functions only. No database access, no LLM calls, no Shot/Asset write,
no image rendering, no ffmpeg.
"""

from __future__ import annotations

from collections.abc import Sequence

from packages.visual.cards import ChapterTitleSpec
from packages.visual.planner import PlannedCard

NARRATION_WPM = 150
CHAPTER_TITLE_SECONDS = 2.5
MIN_CARD_SECONDS = 1.5
MAX_CARD_SECONDS = 20.0


def duration_for_words(word_count: int, wpm: int = NARRATION_WPM) -> float:
    """Seconds of narration for word_count words at wpm. Rounded to 3
    decimal places. Not clamped here -- clamping is assign_durations'
    job; this function reports what an unclamped duration actually is,
    which assign_durations needs before it can decide whether a clamp
    even applies."""
    return round((word_count / wpm) * 60.0, 3)


def _word_count(text: str) -> int:
    return len(text.split())


def _statement_text(card: PlannedCard) -> str:
    spec = card.spec
    if isinstance(spec, ChapterTitleSpec):
        raise AssertionError(f"chapter_title card has no statement text: {card!r}")
    return spec.statement


def assign_durations(cards: Sequence[PlannedCard]) -> list[float]:
    """One duration per card, same order as `cards`.

    Chapter titles carry no narration -- fixed at CHAPTER_TITLE_SECONDS.
    Every other card's duration comes from its spec's statement word
    count at NARRATION_WPM, then clamped to
    [MIN_CARD_SECONDS, MAX_CARD_SECONDS].

    The clamps are guards against pathological input, not shaping
    rules: on real claim data (8-31 words, `docs/HANDOFF.md` sec 11's
    measured range) neither should ever fire -- 8 words is 3.2s, 31
    words is 12.4s, both well inside the clamp bounds. If MAX_CARD_SECONDS
    ever does fire on real input, that is a desync, not a trim: the
    card's image ends at 20.0s while the narration audio (word-count-based
    duration used elsewhere, e.g. total_runtime) is still longer than
    that, so downstream consumers must not treat a clamped duration as
    if it were the narration's real length.
    """
    durations: list[float] = []
    for card in cards:
        if card.kind == "chapter_title":
            durations.append(CHAPTER_TITLE_SECONDS)
            continue
        words = _word_count(_statement_text(card))
        seconds = duration_for_words(words)
        clamped = min(max(seconds, MIN_CARD_SECONDS), MAX_CARD_SECONDS)
        durations.append(round(clamped, 3))
    return durations


def total_runtime(durations: Sequence[float]) -> float:
    return round(sum(durations), 3)
