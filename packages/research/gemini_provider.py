"""Google AI Studio's free-tier Gemini -- see docs/SCHEMA.md for why: no
API credit purchased yet, the 1M-token context window takes a long court
filing in one call with no chunking, and structured output against a
JSON schema is supported. The one implementation of
packages.research.llm_provider.ClaimExtractionProvider that exists today;
see that module's docstring for why nothing else in packages/research/
imports this file directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel

from packages.research.llm_provider import ProposedClaim, TruncatedExtractionError

# "gemini-2.5-flash" and "gemini-2.5-flash-lite" both 404 live on this
# account ("no longer available to new users") despite still appearing in
# models.list() -- confirmed against the real API, not documentation,
# while validating this module. The "-latest" alias is Google's own
# indirection against exactly this churn; use it rather than pinning a
# dated model string that can be quietly cut off for new accounts.
DEFAULT_MODEL = "gemini-flash-latest"

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
  - "fact": a directly established fact about what happened, or the
    adjudicating court/tribunal's own determination, supported by a
    primary or authoritative record.
  - "contemporaneous_report": an assertion the source is reporting that
    someone made -- a period source (e.g. a newspaper) reporting an event,
    but just as much a party's argument, a witness's testimony, or an
    official's allegation reported anywhere, including inside an
    otherwise-authoritative document. The source establishes that the
    statement was made, not that its content is true.
  - "inference": a conclusion you are drawing by connecting things stated
    in the source, rather than something the source states outright.
  Never use any other value.

  The most reliable signal is WHO is the subject of the verb, not the
  verb alone or the source's tier:
  - If the subject making the statement is a PARTY or WITNESS -- verbs
    like argues, testified, alleged, claimed, contended, stated, said --
    that is "contemporaneous_report", regardless of the source's tier.
    Even a primary-record document reports party arguments and witness
    testimony that are not thereby adjudicated facts just because the
    document holding them is authoritative.
  - If the subject is the COURT or TRIBUNAL itself -- verbs like holds,
    finds, concludes, rules, orders, affirms, reverses -- that is "fact":
    the court's own determination is the adjudicated record, not a report
    of what someone else claimed.
  Worked examples from a real appellate opinion:
    "On appeal, Long argues the trial court abused its discretion..."
      -> contemporaneous_report (Long is the subject; this is his
         contention)
    "...minor child testified that Long touched her..."
      -> contemporaneous_report (the witness is the subject; this is
         testimony, not an adjudicated fact)
    "We hold the trial court did not abuse its discretion..."
      -> fact (the court is the subject; this is the ruling itself)
    "Antonio Long appeals his convictions for voluntary manslaughter..."
      -> fact (a plain procedural statement -- an appeal was filed,
         sentences were imposed -- not a contention by either party)

  If you are still unsure after applying that check, choose the more
  cautious of the two, in this order, least to most confident: inference,
  contemporaneous_report, fact. Overstating confidence is the worse
  mistake.
- category: exactly one of "event", "person", "location", "timeline",
  "evidence", "legal_outcome" -- whichever the claim is primarily about.
- date_anchor: an ISO 8601 date (YYYY-MM-DD) if the claim is clearly
  anchored to a specific date, otherwise null. Do not guess a date that
  is not actually supported by the text.

You will also be told the source's own tier (e.g. "primary_record",
"contemporaneous", "retrospective", "unverified"). This is a second,
independent check, not a replacement for the subject-of-the-verb check
above: an unattributed direct statement in a primary_record source leans
"fact"; the same kind of statement in a contemporaneous or retrospective
source leans "contemporaneous_report", because the source itself is
reporting, not adjudicating. Apply both checks -- tier does not override
who is actually making the statement within the text.

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


@dataclass(frozen=True)
class RequestPreview:
    """What extract_claims() would send, without sending it -- for a human
    to inspect before spending a real call, not part of
    ClaimExtractionProvider's interface (Gemini-specific, request-shape
    debugging only)."""

    system_instruction: str
    contents: str


class GeminiClaimExtractor:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def preview_request(self, source_text: str, source_tier: str) -> RequestPreview:
        return RequestPreview(
            system_instruction=_SYSTEM_INSTRUCTION,
            contents=_build_contents(source_text, source_tier),
        )

    async def count_tokens(self, source_text: str, source_tier: str) -> int:
        """Real token count via Gemini's free count_tokens endpoint --
        not a generation call, nothing billed against the free tier's
        request quota. CountTokensConfig.system_instruction is rejected
        outright on the Gemini Developer API (API-key auth) -- "only
        supported in Gemini Enterprise Agent Platform mode", confirmed
        by hitting the real error -- so the system instruction is
        concatenated into the counted text instead of passed via config.
        Slightly different tokenization than the real request's separate
        system_instruction field, close enough for an estimate."""
        response = await self._client.aio.models.count_tokens(
            model=self._model,
            contents=_SYSTEM_INSTRUCTION + "\n\n" + _build_contents(source_text, source_tier),
        )
        return response.total_tokens or 0

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
            contents=_build_contents(source_text, source_tier),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_ExtractionResponseModel,
                max_output_tokens=max_output_tokens,
            ),
        )


def _build_contents(source_text: str, source_tier: str) -> str:
    return f"Source tier: {source_tier}\n\nSource text:\n{source_text}"


def _is_truncated(response: types.GenerateContentResponse) -> bool:
    candidates = response.candidates or []
    return any(c.finish_reason == types.FinishReason.MAX_TOKENS for c in candidates)
