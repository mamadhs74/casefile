"""packages/script/composition.py: the step-3 orchestration layer that
calls a CompositionProvider for one section and reports the word-count
gap against budget (rule 4).

Uses a fake provider (packages.script.composition_provider.CompositionProvider
is a Protocol precisely so tests never need a real Gemini call) -- same
pattern as tests/test_claim_extraction.py's _FakeProvider.
"""

from __future__ import annotations

import pytest

from packages.script.composition import compose_section_text
from packages.script.composition_provider import (
    ClaimForComposition,
    ComposedSection,
    TruncatedCompositionError,
)


class _FakeCompositionProvider:
    def __init__(self, text: str = "", *, raises: Exception | None = None) -> None:
        self._text = text
        self._raises = raises
        self.calls = 0
        self.last_claims: list[ClaimForComposition] | None = None
        self.last_thesis: str | None = None
        self.last_word_budget: int | None = None

    async def compose_section(
        self, claims: list[ClaimForComposition], thesis: str, word_budget: int
    ) -> ComposedSection:
        self.calls += 1
        self.last_claims = claims
        self.last_thesis = thesis
        self.last_word_budget = word_budget
        if self._raises is not None:
            raise self._raises
        return ComposedSection(text=self._text)


def _claim(**overrides: object) -> ClaimForComposition:
    defaults: dict[str, object] = dict(
        claim_id=1,
        statement="The jury returned a verdict of not guilty.",
        claim_type="fact",
        confidence="established",
        date_anchor="1893-06-20",
        thesis_bearing=True,
    )
    defaults.update(overrides)
    return ClaimForComposition(**defaults)  # type: ignore[arg-type]


async def test_compose_section_text_happy_path() -> None:
    provider = _FakeCompositionProvider(text="Four words here now.")
    claims = [_claim()]

    result = await compose_section_text(provider, claims, "A real thesis.", word_budget=100)

    assert result.text == "Four words here now."
    assert result.actual_word_count == 4
    assert result.budgeted_word_count == 100
    assert provider.calls == 1
    assert provider.last_claims == claims
    assert provider.last_thesis == "A real thesis."
    assert provider.last_word_budget == 100


async def test_compose_section_text_passes_empty_claims_through_for_return() -> None:
    """Return's paraphrase mode lives in the provider/prompt, not here --
    this orchestration layer does no special-casing on an empty claims
    list, it's a pure passthrough."""
    provider = _FakeCompositionProvider(text="Paraphrased thesis text.")

    result = await compose_section_text(provider, [], "A real thesis.", word_budget=50)

    assert provider.last_claims == []
    assert result.text == "Paraphrased thesis text."
    assert result.actual_word_count == 3
    assert result.budgeted_word_count == 50


async def test_compose_section_text_reports_actual_below_budget() -> None:
    """Rule 4 stays checked-and-reported: a real gap between actual and
    budgeted is visible on the result, not hidden or corrected."""
    provider = _FakeCompositionProvider(text="Short.")

    result = await compose_section_text(provider, [], "A real thesis.", word_budget=500)

    assert result.actual_word_count == 1
    assert result.budgeted_word_count == 500
    assert result.actual_word_count < result.budgeted_word_count


async def test_compose_section_text_propagates_provider_errors() -> None:
    """No retry happens in this layer -- a provider failure (including
    TruncatedCompositionError after the provider's own internal retry
    already failed) propagates as-is, not swallowed or re-attempted."""
    provider = _FakeCompositionProvider(raises=TruncatedCompositionError("still truncated"))

    with pytest.raises(TruncatedCompositionError):
        await compose_section_text(provider, [_claim()], "A real thesis.", word_budget=50)

    assert provider.calls == 1
