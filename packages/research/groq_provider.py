"""Groq's OpenAI-compatible chat-completions endpoint -- second
implementation of packages.research.llm_provider.ClaimExtractionProvider,
added alongside gemini_provider.py (not replacing it -- see the task
this was built under: no automatic failover, provider is selected
explicitly by the caller).

Same shape as gemini_provider.py on purpose: same system instruction
content (duplicated, not imported -- same reasoning
packages/script/groq_composition_provider.py already documents: each
provider module stays self-contained, free of a cross-provider
dependency), same two-tier truncation retry. The only real difference
is transport -- Groq speaks the OpenAI chat-completions wire format
over plain HTTP (https://api.groq.com/openai/v1/chat/completions), so
this module uses httpx directly (already a project dependency, see
packages/research/fetch.py) instead of a vendor SDK.

MODEL NAME COMES FROM CONFIG, NOT FROM THIS FILE. Unlike
GeminiClaimExtractor (which has a DEFAULT_MODEL fallback baked into
the module), `model` here has no default -- it is a required
constructor argument. The caller (scripts/extract_claims.py) is the
one place that reads GROQ_MODEL out of the environment; if that
variable is unset, the caller fails before this class is ever
constructed. This is deliberate, per the task this was built under.

Does not modify claim_extraction.py, llm_provider.py's
ClaimExtractionProvider protocol, or gemini_provider.py -- this class
satisfies the existing protocol structurally, nothing upstream needed
to change.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ValidationError

from packages.research.llm_provider import (
    ExtractionProviderError,
    ProposedClaim,
    TruncatedExtractionError,
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

DEFAULT_MAX_OUTPUT_TOKENS = 8192
RETRY_MAX_OUTPUT_TOKENS = 16384

_REQUEST_TIMEOUT_SECONDS = 60.0

# Identical wording to gemini_provider.py's own _SYSTEM_INSTRUCTION, plus
# one appended paragraph telling the model how to shape its JSON
# response -- duplicated, not imported, same reasoning
# groq_composition_provider.py already documents for the composition
# side. Keep the two in sync by hand if the extraction prompt changes.
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
  - If the subject is the COURT, JURY, or TRIBUNAL itself -- verbs like
    holds, finds, concludes, rules, orders, affirms, reverses, or a jury
    returning or delivering its verdict -- that is "fact": this is the
    adjudicating body's own determination, not a report of what someone
    else claimed. A jury's verdict is exactly as adjudicative as a
    judge's ruling; both are the record's own conclusion, not a party's
    contention.
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
  Worked example from a real trial newspaper account:
    "Foreman-Not guilty."
      -> fact (the jury -- the adjudicating body for the facts of the
         case -- delivering its own verdict; the same category as a
         judge's ruling, not a party's claim, even though a newspaper
         is the one reporting it)

  Do not skip a passage because the claim it describes is contested,
  disputed, or unproven -- that is not the same thing as "not supported
  by the text." A contested claim is fully supported once you narrow the
  assertion to what the text actually establishes: not "the barn story
  is true or false" but "the prosecutor argued the defendant's
  barn/hayloft account was not credible." That someone made an argument,
  raised a theory, or disputed another party's account is itself a
  plain, directly quotable fact about the record, extractable the same
  as anything else -- as "contemporaneous_report" (their argument or
  claim) or "inference" (your own synthesis of the dispute), never as
  "fact" for the disputed content itself. Caution means picking the
  right claim_type for contested material, not omitting it.
  Worked example:
    "He was evidently convinced that she wore the Bedford cord and
    subsequently burned it, and in accounting for the fact that the
    police did not find the dress at the time of their thorough search,
    he said they were not especially careful, because they believed
    they had the dress they wanted in their possession."
      -> contemporaneous_report ("The prosecutor argued that Borden had
         worn and later burned the Bedford cord dress, and explained the
         police's failure to find it as a result of their not searching
         carefully.") -- extractable precisely because a real argument
         was made and is quotable, not because whether she actually
         burned the dress is established either way.

  If you are still unsure after applying these checks, choose the more
  cautious of the two, in this order, least to most confident: inference,
  contemporaneous_report, fact. Overstating confidence is the worse
  mistake -- but choosing not to extract a contested claim at all is not
  "caution," it is an omission, and omissions are exactly what this
  instruction is meant to prevent for genuinely unsupported invention,
  not for real, quotable disagreements that are already in the text.
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

category must be EXACTLY one of these six words, spelled exactly this
way, and no other word, ever: "event", "person", "location", "timeline",
"evidence", "legal_outcome". claim_type must be EXACTLY one of these
three words, and no other word, ever: "fact", "contemporaneous_report",
"inference". Do not invent a new category or claim_type word that seems
more descriptive of the specific claim -- a claim about a subscriber
count, revenue figure, or profit figure is "evidence" (a specific data
point being cited) or "event" (something that happened, e.g. a deal
closing or a metric being disclosed), never "subscriber", "revenue",
"profit", "financial", "metric", or any other word outside the six
listed above. If none of the six seems like a perfect fit, choose the
closest one from the list -- an imperfect fit from the list is correct;
a new word outside the list is not, no matter how accurate it sounds.

Respond with a single JSON object of the exact shape
{"claims": [{"assertion": "...", "quoted_span": "...", "claim_type":
"...", "category": "...", "date_anchor": "..." or null}, ...]} and
nothing else -- no surrounding markdown, no code fence. An empty list
is {"claims": []}, not an omitted key.
"""


class _ProposedClaimModel(BaseModel):
    """claim_type/category are plain str, NOT Literal -- unlike
    gemini_provider.py's own _ProposedClaimModel. Gemini's
    response_schema enforces its Literal types server-side, so an
    out-of-vocabulary value is structurally impossible there. Groq's
    "json_object" mode has no equivalent server-side enforcement --
    it's a prompt instruction, not a schema constraint -- so the model
    can and does emit values like "profit" or "subscriber" instead of
    a recognized category. Validating that strictly here would crash
    the whole batch on one bad candidate; passing the raw string
    through instead lets claim_extraction.py's own existing defensive
    check (step 3d in that module's docstring: "reject if claim_type
    or category isn't a recognized value") do exactly the job it
    already exists for, per-candidate, without this module changing at
    all. Confirmed necessary empirically, not by inspection: the first
    real Groq run against source 15 threw 14 validation errors this
    way before this fix."""

    assertion: str
    quoted_span: str
    claim_type: str
    category: str
    date_anchor: str | None = None


class _ExtractionResponseModel(BaseModel):
    claims: list[_ProposedClaimModel]


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
    """Mirrors gemini_provider.py's own RequestPreview -- what
    extract_claims() would send, without sending it. Groq-specific,
    request-shape debugging only, not part of ClaimExtractionProvider's
    interface."""

    system_instruction: str
    contents: str


class GroqClaimExtractor:
    def __init__(self, api_key: str, model: str) -> None:
        self._model = model
        self._client = httpx.AsyncClient(
            base_url=GROQ_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )

    def preview_request(self, source_text: str, source_tier: str) -> RequestPreview:
        return RequestPreview(
            system_instruction=_SYSTEM_INSTRUCTION,
            contents=_build_contents(source_text, source_tier),
        )

    async def extract_claims(self, source_text: str, source_tier: str) -> list[ProposedClaim]:
        response = await self._generate(source_text, source_tier, DEFAULT_MAX_OUTPUT_TOKENS)

        if _is_truncated(response):
            # One retry at a higher ceiling -- same contract as
            # TruncatedExtractionError's docstring and gemini_provider.py's
            # own implementation of it.
            response = await self._generate(source_text, source_tier, RETRY_MAX_OUTPUT_TOKENS)
            if _is_truncated(response):
                raise TruncatedExtractionError(
                    f"still truncated at {RETRY_MAX_OUTPUT_TOKENS} max_output_tokens"
                )

        content = response.choices[0].message.content
        try:
            parsed = _ExtractionResponseModel.model_validate_json(content)
        except ValidationError as exc:
            raise TruncatedExtractionError(
                f"response did not parse against the claim schema: {exc}"
            ) from exc

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
    ) -> _GroqChatResponse:
        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_INSTRUCTION},
                        {"role": "user", "content": _build_contents(source_text, source_tier)},
                    ],
                    "response_format": {"type": "json_object"},
                    "max_tokens": max_output_tokens,
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExtractionProviderError(f"Groq request failed: {exc}") from exc
        try:
            return _GroqChatResponse.model_validate(response.json())
        except ValidationError as exc:
            raise ExtractionProviderError(
                f"Groq response did not match the expected chat-completions shape: {exc}"
            ) from exc


def _build_contents(source_text: str, source_tier: str) -> str:
    return f"Source tier: {source_tier}\n\nSource text:\n{source_text}"


def _is_truncated(response: _GroqChatResponse) -> bool:
    return any(choice.finish_reason == "length" for choice in response.choices)
