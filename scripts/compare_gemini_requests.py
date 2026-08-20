"""Compare diagnose_gemini_503.py's request against each of
compose_episode's real requests for episode 1, WITHOUT calling Gemini --
prompted by the diagnostic succeeding while compose_subject10_episode.py
503'd minutes later (docs/HANDOFF.md), which rules out a uniformly-down
tier and points at some difference between the two requests instead.

Builds the exact same request contents compose_episode would send, using
the same private helpers (_SYSTEM_INSTRUCTION, _build_contents) and the
same call sequence/arguments chronological_composition.py itself uses
(Sequence, Return, Ground, Resolution, in that order, each keyed to
Episode.thesis and generate_script's real per-section word budgets) --
but never constructs a genai.Client and never calls generate_content.
generate_script itself is free and local (no network call), so running
it here to get the real claim/thesis/budget inputs costs nothing.

Usage:
    uv run python -m scripts.compare_gemini_requests
"""

from __future__ import annotations

from packages.db.session import get_session
from packages.script.chronological import generate_script
from packages.script.composition_provider import ClaimForComposition
from packages.script.gemini_composition_provider import (
    _SYSTEM_INSTRUCTION,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_MODEL,
    _build_contents,
)
from scripts.diagnose_gemini_503 import _DIAGNOSTIC_CLAIM, _DIAGNOSTIC_THESIS

EPISODE_ID = 1
MIN_CLAIM_COUNT = 11


def _describe(
    label: str,
    claims: list[ClaimForComposition],
    thesis: str,
    word_budget: int,
) -> None:
    contents = _build_contents(claims, thesis, word_budget)
    system_chars = len(_SYSTEM_INSTRUCTION)
    contents_chars = len(contents)
    total_chars = system_chars + contents_chars

    print(f"--- {label} ---")
    print(f"  model:                    {DEFAULT_MODEL}")
    print(f"  claim count:              {len(claims)}")
    print(f"  thesis chars:             {len(thesis)}")
    print(f"  word_budget:              {word_budget}")
    print(f"  system_instruction chars: {system_chars}")
    print(f"  contents chars:           {contents_chars}")
    print(f"  total prompt chars:       {total_chars}")
    print("  generation config:")
    print("    response_mime_type:     application/json")
    print("    response_schema:        _ComposedSectionModel (text: str)")
    print(f"    max_output_tokens:      {DEFAULT_MAX_OUTPUT_TOKENS}")
    print()


def main() -> int:
    _describe(
        "(a) diagnose_gemini_503.py",
        [_DIAGNOSTIC_CLAIM],
        _DIAGNOSTIC_THESIS,
        10,
    )

    with get_session() as session:
        allocated = generate_script(session, EPISODE_ID, min_claim_count=MIN_CLAIM_COUNT)

    _describe(
        "(b1) compose_episode -- Sequence",
        allocated.sequence_claims,
        allocated.thesis,
        allocated.budgeted_word_counts.sequence,
    )
    _describe(
        "(b2) compose_episode -- Return",
        [],
        allocated.thesis,
        allocated.budgeted_word_counts.return_,
    )
    if allocated.ground_claims:
        _describe(
            "(b3) compose_episode -- Ground",
            allocated.ground_claims,
            allocated.thesis,
            allocated.budgeted_word_counts.ground,
        )
    if allocated.resolution_claims:
        _describe(
            "(b4) compose_episode -- Resolution",
            allocated.resolution_claims,
            allocated.thesis,
            allocated.budgeted_word_counts.resolution,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
