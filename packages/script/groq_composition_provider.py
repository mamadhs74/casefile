"""Groq's OpenAI-compatible chat-completions endpoint -- second
implementation of packages.script.composition_provider.CompositionProvider,
added alongside gemini_composition_provider.py (not replacing it -- see
the task this was built under: no automatic failover, provider is
selected explicitly by the caller).

Same shape as gemini_composition_provider.py on purpose: same system
instruction content, same claims-block/contents builders, same
two-tier truncation retry. The only real difference is transport --
Groq speaks the OpenAI chat-completions wire format over plain HTTP
(https://api.groq.com/openai/v1/chat/completions), so this module uses
httpx directly (already a project dependency, see packages/research/
fetch.py) instead of a vendor SDK.

MODEL NAME COMES FROM CONFIG, NOT FROM THIS FILE. Unlike
GeminiCompositionProvider (which has a DEFAULT_MODEL fallback baked
into the module), `model` here has no default -- it is a required
constructor argument. The caller (scripts/compose_episode.py) is the
one place that reads GROQ_MODEL out of the environment; if that
variable is unset, the caller fails before this class is ever
constructed. This is deliberate, per the task this was built under.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ValidationError

from packages.script.composition_provider import (
    ClaimForComposition,
    ComposedSection,
    CompositionProviderError,
    TruncatedCompositionError,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

DEFAULT_MAX_OUTPUT_TOKENS = 8192
RETRY_MAX_OUTPUT_TOKENS = 16384

_REQUEST_TIMEOUT_SECONDS = 60.0

# Identical wording to gemini_composition_provider.py's own
# _SYSTEM_INSTRUCTION -- duplicated, not imported, so each provider
# module stays self-contained and free of a cross-provider dependency
# (see composition_provider.py's own docstring: nothing outside a
# provider module should need to know another provider exists). Keep
# these two in sync by hand if the prompt changes; that's the cost of
# the two providers producing comparable output.
_SYSTEM_INSTRUCTION = """\
You compose narration for one section of a documentary episode, from a
fixed list of claims, for a true-crime/historical documentary pipeline.
You are not researching or verifying anything -- every claim you are
given is already established. Your only job is to write prose that
states them, in order, within a word budget.

You will receive:
- A list of claims. Each has: a statement, a claim_type ("fact",
  "contemporaneous_report", or "inference"), a confidence
  ("established", "reported", or "contested"), a date_anchor (may be
  absent), thesis_bearing (true or false), and a word_target -- the
  number of words to spend on that specific claim.
- The episode's thesis -- the argument this episode is making. Not a
  claim to restate; context for tone and emphasis.
- A target word count for this section as a whole.

Two rules that override everything else:

1. Never state anything not present in the claims you were given. Do not
   add color, motive, speculation, or connective narrative detail that
   isn't in a claim's own statement. If the claims feel thin, the
   narration is thin -- that is correct, not a problem to solve by
   inventing texture.

2. Preserve claim_type and confidence in how you phrase each claim --
   this is the same distinction claim extraction draws, just applied in
   reverse. You are not deciding a claim's type here, you are being
   handed one and must not erase it in the writing:
   - "fact" / "established": state it plainly. "The jury returned a
     verdict of not guilty."
   - "contemporaneous_report" / "reported": attribute it. Someone said,
     testified, argued, or reported it -- the claim is that the
     statement was made, not that its content is settled. "Bridget
     Sullivan testified that she heard no quarrels in the household," not
     "There were no quarrels in the household."
   - "contested": if you ever receive one, name that it is disputed
     rather than picking a side. This should not come up yet -- no
     source produces a contested claim today -- but if it does, do not
     silently resolve the dispute by choosing one account.
   Flattening a reported claim into a stated fact is the single most
   damaging thing you can do here -- it is exactly the distinction the
   rest of this pipeline exists to preserve.

Word allocation within the section:
- A claim's word_target is earned by developing it against the other
  claims in the section, not by restating it. A claim with a large
  word_target should draw in the claims around it -- connect them to
  it, subordinate them to it, make them part of its account -- so those
  claims are covered inside that passage rather than written out again
  as separate sentences of their own later. A claim with a small
  word_target (roughly one sentence's worth) should be stated once,
  plainly, and left alone.
- Never state the same fact twice in different words, for any claim, at
  any word_target. If a claim cannot reach its word_target without
  repeating something already said, write it once and stop -- under-
  running a target is correct, restating a fact to pad toward it is
  not.
- The section-level target word count is the sum these per-claim
  targets should land near once you add them all up. If the two ever
  seem in tension, follow each claim's own word_target and the no-
  repetition rule above -- never restate a claim just to move the
  section's total closer to its target.

If the claims list is empty, this is the Return section, a different
task: paraphrase the given thesis in your own words, in the narrator's
voice, restating what the composed sections already established -- do
not restate the thesis verbatim, do not introduce any claim or fact not
already stated elsewhere, no moral, no address to the viewer ("you might
be wondering..."). Restate what was shown; do not make the case for it.
You may not characterize any line of evidence as insufficient,
inconclusive, or secondary, and you may not argue for why the thesis is
correct -- if no claim you were given says a piece of evidence failed to
settle something, you may not say it either.

Order claims within the section in the order given -- do not reorder
them. Output plain prose only: no headings, no claim IDs, no markdown,
no bullet points.

Respond with a single JSON object of the exact shape {"text": "<the
composed prose>"} and nothing else -- no surrounding markdown, no code
fence.
"""


class _ComposedSectionModel(BaseModel):
    text: str


class _GroqMessage(BaseModel):
    content: str


class _GroqChoice(BaseModel):
    finish_reason: str
    message: _GroqMessage


class _GroqChatResponse(BaseModel):
    """Only the fields this module reads from a chat-completions
    response -- not a full schema of Groq's API."""

    choices: list[_GroqChoice]


@dataclass(frozen=True)
class RequestPreview:
    """Mirrors gemini_composition_provider.py's own RequestPreview --
    what compose_section() would send, without sending it."""

    system_instruction: str
    contents: str


class GroqCompositionProvider:
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=GROQ_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )

    def preview_request(
        self, claims: list[ClaimForComposition], thesis: str, word_budget: int
    ) -> RequestPreview:
        return RequestPreview(
            system_instruction=_SYSTEM_INSTRUCTION,
            contents=_build_contents(claims, thesis, word_budget),
        )

    async def compose_section(
        self, claims: list[ClaimForComposition], thesis: str, word_budget: int
    ) -> ComposedSection:
        response = await self._generate(claims, thesis, word_budget, DEFAULT_MAX_OUTPUT_TOKENS)

        if _is_truncated(response):
            # One retry at a higher ceiling before raising -- same
            # contract as TruncatedCompositionError's docstring and
            # gemini_composition_provider.py's own implementation of it.
            response = await self._generate(
                claims, thesis, word_budget, RETRY_MAX_OUTPUT_TOKENS
            )
            if _is_truncated(response):
                raise TruncatedCompositionError(
                    f"still truncated at {RETRY_MAX_OUTPUT_TOKENS} max_output_tokens"
                )

        content = response.choices[0].message.content
        try:
            parsed = _ComposedSectionModel.model_validate_json(content)
        except ValidationError as exc:
            raise TruncatedCompositionError(
                f"response did not parse against the composition schema: {exc}"
            ) from exc

        return ComposedSection(text=parsed.text)

    async def _generate(
        self,
        claims: list[ClaimForComposition],
        thesis: str,
        word_budget: int,
        max_output_tokens: int,
    ) -> _GroqChatResponse:
        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_INSTRUCTION},
                        {
                            "role": "user",
                            "content": _build_contents(claims, thesis, word_budget),
                        },
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": max_output_tokens,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CompositionProviderError(f"Groq request failed: {exc}") from exc
        try:
            return _GroqChatResponse.model_validate(response.json())
        except ValidationError as exc:
            raise CompositionProviderError(
                f"Groq response did not match the expected chat-completions shape: {exc}"
            ) from exc


def _build_claims_block(claims: list[ClaimForComposition]) -> str:
    if not claims:
        return "Claims: none -- this is the Return section, see the paraphrase instructions."
    lines = ["Claims, in order:"]
    for c in claims:
        date_part = f", date_anchor={c.date_anchor}" if c.date_anchor else ""
        lines.append(
            f'- claim_type={c.claim_type}, confidence={c.confidence}, '
            f'thesis_bearing={c.thesis_bearing}, word_target={c.word_target}'
            f'{date_part}: "{c.statement}"'
        )
    return "\n".join(lines)


def _build_contents(claims: list[ClaimForComposition], thesis: str, word_budget: int) -> str:
    return (
        f"Episode thesis: {thesis}\n\n"
        f"Target word count for this section: {word_budget}\n\n"
        f"{_build_claims_block(claims)}"
    )


def _is_truncated(response: _GroqChatResponse) -> bool:
    return any(choice.finish_reason == "length" for choice in response.choices)
