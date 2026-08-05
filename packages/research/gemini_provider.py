"""Google AI Studio's free-tier Gemini -- see docs/SCHEMA.md for why: no
API credit purchased yet, the 1M-token context window takes a long court
filing in one call with no chunking, and structured output against a
JSON schema is supported. The one implementation of
packages.research.llm_provider.ClaimExtractionProvider that exists today;
see that module's docstring for why nothing else in packages/research/
imports this file directly.
"""

from __future__ import annotations

from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel

from packages.research.llm_provider import ProposedClaim, TruncatedExtractionError

DEFAULT_MODEL = "gemini-2.5-flash"

DEFAULT_MAX_OUTPUT_TOKENS = 8192
RETRY_MAX_OUTPUT_TOKENS = 16384

_SYSTEM_INSTRUCTION = """\
You extract factual claims from a single historical or true-crime source
document, for a documentary research pipeline. Read the source text and
produce a list of discrete, independently verifiable claims.

For every claim, provide:
- assertion: one clear sentence stating the claim.
- quoted_span: the EXACT passage from the source text that supports this
  claim, copied VERBATIM -- character for character, including original
  punctuation and spelling. Do not paraphrase, summarize, correct, or
  clean up the quote in any way. Keep it as short as possible while still
  fully supporting the assertion -- ideally one sentence, at most a couple
  of sentences. A human reviewer will look up this exact string in the
  source text to verify your claim in seconds; if it is not an exact
  substring, or if it is too long to read at a glance, the claim is
  discarded before it is ever used.
- claim_type: exactly one of:
  - "fact": a directly established fact about what happened, supported by
    a primary or authoritative record.
  - "contemporaneous_report": what a period source (e.g. a newspaper)
    reported at the time, as distinct from an adjudicated fact. Prefer
    this over "fact" for anything from a period news source, EVEN IF it is
    phrased with total confidence and no hedging language -- newspapers
    report, they do not adjudicate, and confident phrasing from a period
    news source is not the same thing as an established fact.
  - "inference": a conclusion you are drawing by connecting things stated
    in the source, rather than something the source states outright.
  Never use any other value. If you are unsure which of these three
  applies, choose the more cautious one in this order, least to most
  confident: inference, contemporaneous_report, fact. Overstating
  confidence is the worse mistake.
- category: exactly one of "event", "person", "location", "timeline",
  "evidence", "legal_outcome" -- whichever the claim is primarily about.
- date_anchor: an ISO 8601 date (YYYY-MM-DD) if the claim is clearly
  anchored to a specific date, otherwise null. Do not guess a date that
  is not actually supported by the text.

You will be told the source's own tier (e.g. "primary_record",
"contemporaneous", "retrospective", "unverified"). Use it as context for
claim_type: an unattributed direct statement in a primary_record source
leans "fact"; the same kind of statement in a contemporaneous or
retrospective source leans "contemporaneous_report", because the source
itself is reporting, not adjudicating.

Do not invent claims not supported by the text. If the source has no
extractable factual content, return an empty list. Do not pad the list to
reach any particular count.
"""


class _ProposedClaimModel(BaseModel):
    assertion: str
    quoted_span: str
    claim_type: Literal["fact", "contemporaneous_report", "inference"]
    category: Literal["event", "person", "location", "timeline", "evidence", "legal_outcome"]
    date_anchor: str | None = None


class _ExtractionResponseModel(BaseModel):
    claims: list[_ProposedClaimModel]


class GeminiClaimExtractor:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def extract_claims(self, source_text: str, source_tier: str) -> list[ProposedClaim]:
        response = await self._generate(source_text, source_tier, DEFAULT_MAX_OUTPUT_TOKENS)

        if _is_truncated(response):
            # One retry at a higher ceiling, per docs/SCHEMA.md -- an
            # unusually claim-dense source is a real, expected case, not
            # a reason to fail outright on the first attempt.
            response = await self._generate(source_text, source_tier, RETRY_MAX_OUTPUT_TOKENS)
            if _is_truncated(response):
                raise TruncatedExtractionError(
                    f"still truncated at {RETRY_MAX_OUTPUT_TOKENS} max_output_tokens"
                )

        parsed = response.parsed
        if not isinstance(parsed, _ExtractionResponseModel):
            raise TruncatedExtractionError("response did not parse against the claim schema")

        return [
            ProposedClaim(
                assertion=c.assertion,
                quoted_span=c.quoted_span,
                claim_type=c.claim_type,
                category=c.category,
                date_anchor=c.date_anchor,
            )
            for c in parsed.claims
        ]

    async def _generate(
        self, source_text: str, source_tier: str, max_output_tokens: int
    ) -> types.GenerateContentResponse:
        return await self._client.aio.models.generate_content(
            model=self._model,
            contents=f"Source tier: {source_tier}\n\nSource text:\n{source_text}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_ExtractionResponseModel,
                max_output_tokens=max_output_tokens,
            ),
        )


def _is_truncated(response: types.GenerateContentResponse) -> bool:
    candidates = response.candidates or []
    return any(c.finish_reason == types.FinishReason.MAX_TOKENS for c in candidates)
