"""Google AI Studio's free-tier Gemini -- same provider, same reasoning as
packages/research/gemini_provider.py (no API credit purchased yet, the
1M-token context window absorbs a long source plus the known-entity
context in one call, structured output against a JSON schema is
supported). The one implementation of
packages.research.entity_provider.EntityExtractionProvider that exists
today; see that module's docstring for why nothing else in
packages/research/ imports this file directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from google import genai
from google.genai import types
from pydantic import BaseModel

from packages.research.entity_provider import (
    KnownEntity,
    ProposedEntity,
    TruncatedEntityExtractionError,
)

# Same model-availability caveat as gemini_provider.py: "-latest" is
# Google's own indirection against dated model strings quietly
# disappearing for new accounts -- confirmed against the real API there,
# not re-verified independently here, but there is no reason this
# provider would be exempt from the same churn.
DEFAULT_MODEL = "gemini-flash-latest"

DEFAULT_MAX_OUTPUT_TOKENS = 8192
RETRY_MAX_OUTPUT_TOKENS = 16384

_SYSTEM_INSTRUCTION = """\
You extract mentions of named people from a single historical or
true-crime source document, for a documentary research pipeline. Read
the source text and identify every distinct person it names or clearly
refers to -- victims, suspects, witnesses, investigators, and
commentators.

You will also be given a list of entities already established for this
same subject from earlier sources, each with an id, name, role, and an
identifying passage from the source that first established them. For
every person you find in THIS source, decide: is this the same person as
one of those known entities, or someone new?

For every person, provide:
- name: the person's name as it appears in this source.
- role: exactly one of "victim", "suspect", "witness", "investigator",
  "commentator" -- whichever best describes their part in this source's
  account. Never use any other value.
- identifying_span: the EXACT passage from the source text that
  identifies this person, copied VERBATIM -- character for character,
  including original punctuation and spelling. Do not paraphrase or clean
  it up. Keep it as short as possible while still clearly identifying
  who this is -- ideally a clause or one sentence. A human reviewer will
  look up this exact string in the source text in seconds; if it is not
  an exact substring, or too long to read at a glance, the mention is
  discarded before it is ever used.
- matched_entity_id: if this person is the same real person as one of
  the known entities listed below, its id. Otherwise null.
- match_rationale: if matched_entity_id is set, one short sentence
  explaining why you believe this is the same person -- what matched
  beyond just the name (role, context, relationship to other people or
  events already described). Null if matched_entity_id is null -- there
  is nothing to explain about someone new.

Matching is the highest-stakes judgment here: two different real people
sharing a name and role is a real, common failure shape for this domain
-- e.g. a mother and daughter both referred to as "Miss Smith", or two
siblings sharing a surname and both described as a witness. A wrong match
folds two distinct people into one identity, which is worse and harder to
undo than a wrong split (which just leaves two separate entities for a
human to merge later). When name and role alone don't clearly
distinguish someone from a known entity -- no matching identifying
detail, contradicting age or relationship, a different source's account
that doesn't line up -- prefer matched_entity_id: null over guessing a
match.

If the same person is mentioned more than once within THIS source,
report them only once, using whichever mention most specifically
identifies who they are as identifying_span.

Do not invent people not named or clearly referred to in the text. If
the source names no one, return an empty list.
"""


class _ProposedEntityModel(BaseModel):
    name: str
    role: Literal["victim", "suspect", "witness", "investigator", "commentator"]
    identifying_span: str
    matched_entity_id: int | None = None
    match_rationale: str | None = None


class _ExtractionResponseModel(BaseModel):
    entities: list[_ProposedEntityModel]


@dataclass(frozen=True)
class RequestPreview:
    """What extract_entities() would send, without sending it -- for a
    human to inspect before spending a real call. Gemini-specific
    request-shape debugging, not part of EntityExtractionProvider's
    interface -- mirrors gemini_provider.py's RequestPreview."""

    system_instruction: str
    contents: str


class GeminiEntityExtractor:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def preview_request(
        self, source_text: str, known_entities: list[KnownEntity]
    ) -> RequestPreview:
        return RequestPreview(
            system_instruction=_SYSTEM_INSTRUCTION,
            contents=_build_contents(source_text, known_entities),
        )

    async def count_tokens(self, source_text: str, known_entities: list[KnownEntity]) -> int:
        """Real token count via Gemini's free count_tokens endpoint -- see
        gemini_provider.py's own count_tokens for why the system
        instruction is concatenated into the counted text rather than
        passed via CountTokensConfig.system_instruction (rejected outright
        on the Gemini Developer API's key auth)."""
        response = await self._client.aio.models.count_tokens(
            model=self._model,
            contents=_SYSTEM_INSTRUCTION
            + "\n\n"
            + _build_contents(source_text, known_entities),
        )
        return response.total_tokens or 0

    async def extract_entities(
        self, source_text: str, known_entities: list[KnownEntity]
    ) -> list[ProposedEntity]:
        response = await self._generate(source_text, known_entities, DEFAULT_MAX_OUTPUT_TOKENS)

        if _is_truncated(response):
            # One retry at a higher ceiling before raising, per the
            # interface's contract -- a source naming many people is a
            # real, expected case, not a reason to fail on the first
            # attempt. See entity_provider.py's
            # TruncatedEntityExtractionError docstring.
            response = await self._generate(source_text, known_entities, RETRY_MAX_OUTPUT_TOKENS)
            if _is_truncated(response):
                raise TruncatedEntityExtractionError(
                    f"still truncated at {RETRY_MAX_OUTPUT_TOKENS} max_output_tokens"
                )

        parsed = response.parsed
        if not isinstance(parsed, _ExtractionResponseModel):
            raise TruncatedEntityExtractionError("response did not parse against the entity schema")

        return [
            ProposedEntity(
                name=e.name,
                role=e.role,
                identifying_span=e.identifying_span,
                matched_entity_id=e.matched_entity_id,
                match_rationale=e.match_rationale,
            )
            for e in parsed.entities
        ]

    async def _generate(
        self, source_text: str, known_entities: list[KnownEntity], max_output_tokens: int
    ) -> types.GenerateContentResponse:
        return await self._client.aio.models.generate_content(
            model=self._model,
            contents=_build_contents(source_text, known_entities),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_ExtractionResponseModel,
                max_output_tokens=max_output_tokens,
            ),
        )


def _build_known_entities_block(known_entities: list[KnownEntity]) -> str:
    if not known_entities:
        return "Known entities already established for this subject: none yet."
    lines = ["Known entities already established for this subject:"]
    for ke in known_entities:
        lines.append(
            f'- id={ke.entity_id}, name="{ke.name}", role={ke.role}, '
            f'identifying_span="{ke.identifying_span}" '
            f'(first identified in source "{ke.source_title}", source_id={ke.source_id})'
        )
    return "\n".join(lines)


def _build_contents(source_text: str, known_entities: list[KnownEntity]) -> str:
    return (
        f"{_build_known_entities_block(known_entities)}\n\nSource text:\n{source_text}"
    )


def _is_truncated(response: types.GenerateContentResponse) -> bool:
    candidates = response.candidates or []
    return any(c.finish_reason == types.FinishReason.MAX_TOKENS for c in candidates)
