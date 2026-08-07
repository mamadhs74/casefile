"""Google AI Studio's free-tier Gemini -- same provider, same reasoning as
packages/research/gemini_provider.py and gemini_entity_provider.py (no API
credit purchased yet, structured output against a JSON schema is
supported). The one implementation of
packages.script.composition_provider.CompositionProvider that exists
today; see that module's docstring for why nothing else in
packages/script/ imports this file directly.

Not called anywhere yet -- packages/script/composition.py is the
orchestration layer that will call it, and nothing wires that into
generate_script yet either. This file is built and lint/type-checked, not
exercised against a real API key.
"""

from __future__ import annotations

from dataclasses import dataclass

from google import genai
from google.genai import types
from pydantic import BaseModel

from packages.script.composition_provider import (
    ClaimForComposition,
    ComposedSection,
    TruncatedCompositionError,
)

# Same model-availability caveat as gemini_provider.py/gemini_entity_provider.py:
# "-latest" is Google's own indirection against dated model strings quietly
# disappearing for new accounts.
DEFAULT_MODEL = "gemini-flash-latest"

DEFAULT_MAX_OUTPUT_TOKENS = 8192
RETRY_MAX_OUTPUT_TOKENS = 16384

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
  absent), and thesis_bearing (true or false).
- The episode's thesis -- the argument this episode is making. Not a
  claim to restate; context for tone and emphasis.
- A target word count for this section.

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
- Claims with thesis_bearing=true: elaborate. Several sentences each,
  with whatever concrete detail that claim's own statement already
  contains -- the number, the name, the physical specifics. These are
  the claims the thesis turns on; give them room.
- Claims with thesis_bearing=false: one sentence each. State it and move
  on. Do not elaborate, do not add setup or transition sentences around
  it.
- Aim for the target word count. It is a target, not a hard limit --
  do not pad with filler to reach it, and do not truncate a
  thesis-bearing claim's detail just to stay under it.

If the claims list is empty, this is the Return section, a different
task: paraphrase the given thesis in your own words, in the narrator's
voice, acknowledging that the events have now been laid out -- do not
restate the thesis verbatim, do not introduce any claim or fact not
already stated elsewhere, no moral, no address to the viewer ("you might
be wondering...").

Order claims within the section in the order given -- do not reorder
them. Output plain prose only: no headings, no claim IDs, no markdown,
no bullet points.
"""


class _ComposedSectionModel(BaseModel):
    text: str


@dataclass(frozen=True)
class RequestPreview:
    """What compose_section() would send, without sending it -- for a
    human to inspect before spending a real call. Mirrors
    gemini_provider.py's/gemini_entity_provider.py's own RequestPreview."""

    system_instruction: str
    contents: str


class GeminiCompositionProvider:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def preview_request(
        self, claims: list[ClaimForComposition], thesis: str, word_budget: int
    ) -> RequestPreview:
        return RequestPreview(
            system_instruction=_SYSTEM_INSTRUCTION,
            contents=_build_contents(claims, thesis, word_budget),
        )

    async def count_tokens(
        self, claims: list[ClaimForComposition], thesis: str, word_budget: int
    ) -> int:
        """Real token count via Gemini's free count_tokens endpoint --
        same reasoning as gemini_provider.py's own count_tokens for why
        the system instruction is concatenated into the counted text
        rather than passed via CountTokensConfig.system_instruction
        (rejected outright on the Gemini Developer API's key auth)."""
        response = await self._client.aio.models.count_tokens(
            model=self._model,
            contents=_SYSTEM_INSTRUCTION + "\n\n" + _build_contents(claims, thesis, word_budget),
        )
        return response.total_tokens or 0

    async def compose_section(
        self, claims: list[ClaimForComposition], thesis: str, word_budget: int
    ) -> ComposedSection:
        response = await self._generate(claims, thesis, word_budget, DEFAULT_MAX_OUTPUT_TOKENS)

        if _is_truncated(response):
            # One retry at a higher ceiling before raising, per the
            # interface's contract -- see composition_provider.py's
            # TruncatedCompositionError docstring.
            response = await self._generate(
                claims, thesis, word_budget, RETRY_MAX_OUTPUT_TOKENS
            )
            if _is_truncated(response):
                raise TruncatedCompositionError(
                    f"still truncated at {RETRY_MAX_OUTPUT_TOKENS} max_output_tokens"
                )

        parsed = response.parsed
        if not isinstance(parsed, _ComposedSectionModel):
            raise TruncatedCompositionError("response did not parse against the composition schema")

        return ComposedSection(text=parsed.text)

    async def _generate(
        self,
        claims: list[ClaimForComposition],
        thesis: str,
        word_budget: int,
        max_output_tokens: int,
    ) -> types.GenerateContentResponse:
        return await self._client.aio.models.generate_content(
            model=self._model,
            contents=_build_contents(claims, thesis, word_budget),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_ComposedSectionModel,
                max_output_tokens=max_output_tokens,
            ),
        )


def _build_claims_block(claims: list[ClaimForComposition]) -> str:
    if not claims:
        return "Claims: none -- this is the Return section, see the paraphrase instructions."
    lines = ["Claims, in order:"]
    for c in claims:
        date_part = f", date_anchor={c.date_anchor}" if c.date_anchor else ""
        lines.append(
            f'- claim_type={c.claim_type}, confidence={c.confidence}, '
            f'thesis_bearing={c.thesis_bearing}{date_part}: "{c.statement}"'
        )
    return "\n".join(lines)


def _build_contents(claims: list[ClaimForComposition], thesis: str, word_budget: int) -> str:
    return (
        f"Episode thesis: {thesis}\n\n"
        f"Target word count for this section: {word_budget}\n\n"
        f"{_build_claims_block(claims)}"
    )


def _is_truncated(response: types.GenerateContentResponse) -> bool:
    candidates = response.candidates or []
    return any(c.finish_reason == types.FinishReason.MAX_TOKENS for c in candidates)
