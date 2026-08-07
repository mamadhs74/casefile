"""Step 3's orchestration layer: calls a CompositionProvider for one
section and reports the word-count gap against budget (rule 4). Deliberately
architecture-agnostic -- turning a claim list + word budget + thesis into
prose via a provider isn't specific to `chronological`; any future
architecture's generator can call this the same way, the same reasoning
`claim_extraction.py` is subject/source-generic rather than living inside
one architecture's own module.

Not wired into packages/script/chronological.py yet. generate_script still
concatenates -- this module exists and is tested against a fake provider,
but nothing calls it from the real generation path. That integration --
whether generate_script grows an optional provider parameter, whether it
has to become async to call one, what happens to its existing synchronous
tests -- is a real design question of its own, not resolved by building
this.

Rule 4 stays checked-and-reported here too, not enforced: this module
returns the actual and budgeted word counts side by side and does not
raise or retry when they disagree. No automatic retry on a budget miss is
built here on purpose -- see docs/HANDOFF.md for why: the cost of a repair
call is only worth deciding once real output shows how far off the first
pass actually lands.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.script.composition_provider import ClaimForComposition, CompositionProvider


@dataclass(frozen=True)
class ComposedSectionResult:
    text: str
    actual_word_count: int
    budgeted_word_count: int


async def compose_section_text(
    provider: CompositionProvider,
    claims: list[ClaimForComposition],
    thesis: str,
    word_budget: int,
) -> ComposedSectionResult:
    """One call to the provider, no retry beyond whatever the provider
    already does internally for truncation (see
    composition_provider.py's TruncatedCompositionError). claims empty is
    valid input, not a special case handled here -- see
    CompositionProvider.compose_section's own docstring for why Return's
    empty-claims paraphrase mode lives in the provider/prompt, not here.
    """
    composed = await provider.compose_section(claims, thesis, word_budget)
    return ComposedSectionResult(
        text=composed.text,
        actual_word_count=_word_count(composed.text),
        budgeted_word_count=word_budget,
    )


def _word_count(text: str) -> int:
    return len(text.split())
