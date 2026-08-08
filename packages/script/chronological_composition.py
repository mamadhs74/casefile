"""Step 3, wired: `chronological`-specific orchestration deciding which
sections need a composition call, and how generate_script's allocation
feeds them. This is the B option -- generate_script stays synchronous
and unchanged in signature and behavior; its return type gained additive
fields (SectionedScript.ground_claims etc., see that class's own
docstring) so this module doesn't have to re-implement allocation to get
at the claims it needs.

Call count is 2-4, never a fixed 4:
- Sequence always gets a call. generate_script unconditionally appends
  the cold-open claim to sequence_claims regardless of its own section
  tag, so Sequence can never be empty.
- Return always gets a call, with an empty claims list -- its paraphrase
  task needs the provider even though it never has claims to compose
  from; empty is its normal input, not a signal to skip.
- Ground and Resolution only get a call if generate_script's allocation
  actually put a claim in them. Skipped (not called with an empty list)
  when empty, same as generate_script's own concatenation-era behavior
  for an empty Ground -- the text stays "".

Rule 4 stays checked-and-reported here too: actual_word_counts is
recomputed from the composed text (composition.compose_section_text does
this per call), not carried over from generate_script's concatenation-era
counts, which describe text this function is about to replace. No retry
on a budget miss -- same reasoning as composition.py.
"""

from __future__ import annotations

from dataclasses import replace

from sqlmodel import Session

from packages.script.chronological import (
    MIN_TOTAL_CLAIM_COUNT,
    SectionedScript,
    SectionWordCounts,
    generate_script,
)
from packages.script.composition import compose_section_text
from packages.script.composition_provider import CompositionProvider


async def compose_episode(
    session: Session,
    episode_id: int,
    provider: CompositionProvider,
    *,
    min_claim_count: int = MIN_TOTAL_CLAIM_COUNT,
) -> SectionedScript:
    """Runs generate_script first, synchronously -- every one of its
    checks (episode exists, render gate, profile exists, narratable,
    rules 6/7, cold open) must already pass before any provider call
    happens. This function adds no validation of its own; a
    generate_script failure propagates unchanged, before any quota is
    spent.
    """
    allocated = generate_script(session, episode_id, min_claim_count=min_claim_count)

    sequence_result = await compose_section_text(
        provider,
        allocated.sequence_claims,
        allocated.thesis,
        allocated.budgeted_word_counts.sequence,
    )
    return_result = await compose_section_text(
        provider, [], allocated.thesis, allocated.budgeted_word_counts.return_
    )

    if allocated.ground_claims:
        ground_result = await compose_section_text(
            provider,
            allocated.ground_claims,
            allocated.thesis,
            allocated.budgeted_word_counts.ground,
        )
        ground_text = ground_result.text
        ground_word_count = ground_result.actual_word_count
    else:
        ground_text = ""
        ground_word_count = 0

    if allocated.resolution_claims:
        resolution_result = await compose_section_text(
            provider,
            allocated.resolution_claims,
            allocated.thesis,
            allocated.budgeted_word_counts.resolution,
        )
        resolution_text = resolution_result.text
        resolution_word_count = resolution_result.actual_word_count
    else:
        resolution_text = ""
        resolution_word_count = 0

    actual_word_counts = SectionWordCounts(
        # Cold Open and Thesis need no call -- Cold Open reuses an
        # existing claim's text, Thesis is Episode.thesis verbatim --
        # so their word counts carry over from generate_script unchanged.
        cold_open=allocated.actual_word_counts.cold_open,
        thesis=allocated.actual_word_counts.thesis,
        ground=ground_word_count,
        sequence=sequence_result.actual_word_count,
        resolution=resolution_word_count,
        return_=return_result.actual_word_count,
    )

    # dataclasses.replace: only the fields composition actually changes
    # are overridden. budgeted_word_counts, untagged_claim_count,
    # cold_open_claim, and the *_claims allocation lists all carry
    # forward from generate_script unchanged -- composition doesn't
    # revise the budget, the tagging report, or the allocation, only the
    # text and the actual-word-count report against it.
    return replace(
        allocated,
        ground=ground_text,
        sequence=sequence_result.text,
        resolution=resolution_text,
        return_=return_result.text,
        actual_word_counts=actual_word_counts,
    )
