"""Google AI Studio's free-tier Gemini -- same provider, same reasoning
as gemini_composition_provider.py. The one implementation of
SectionTaggingProvider that exists today.

The GROUND-vs-RESOLUTION-vs-null distinction is given as fixed rules
(see the task this was built under), but the RESOLUTION rule has a real
subtlety a plain instruction doesn't reliably convey on its own --
"settled outcome, past tense" sounds like it should exclude a still-open
thread, but docs/ARCHITECTURES.md sec 3's own unresolved-threads clause
says the opposite: naming an unresolved thread IS resolution material.
The worked examples below are the two real claims (subject 10, source
13) whose distinction this rule turns on, hand-classified already this
session -- not invented for this prompt.
"""

from __future__ import annotations

from google import genai
from google.genai import types
from pydantic import BaseModel

from packages.script.section_tagging_provider import (
    ClaimForTagging,
    MismatchedClaimIdsError,
    SectionTaggingProviderError,
    TaggedClaim,
    TooManyGroundClaimsError,
)

DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_MAX_OUTPUT_TOKENS = 8192

_SYSTEM_INSTRUCTION = """\
You are tagging claims from ONE source (one article or document) for a
documentary pipeline. Every claim you are given comes from the same
source and describes the same story. Assign each claim a `section`:
"GROUND", "RESOLUTION", or null.

GROUND -- at most one claim per source. The claim establishing who did
what, at what scale, that the other claims build on: the setup, not a
detail. If no single claim clearly plays this role, tag none of them
GROUND. Never tag more than one claim GROUND for this source.

RESOLUTION -- a settled outcome, stated in the past tense: something
that actually happened, was decided, or was found -- not something
expected or anticipated to happen. A pending or expected step is NOT
resolution, even if it sounds conclusive ("is expected to approve") --
it hasn't happened yet. A named, still-open thread -- something
unresolved that is itself worth naming as unresolved, like a threatened
lawsuit or an ongoing dispute -- IS resolution, because naming what the
record does NOT yet settle is part of what Resolution does.

Worked examples, both from the same real source, showing this exact
distinction:
- "The Financial Times reported that the European Commission is
  expected to approve the merger with a condition..." -- NOT
  resolution. "Expected to approve" is anticipated, not settled; this
  is null.
- "A state coalition led by California is preparing a lawsuit expected
  within a month to challenge and block the merger." -- IS resolution.
  This is a named, still-open thread: the record doesn't say the deal
  is safe, it says a specific, real challenge is coming. Naming that
  clearly is exactly what Resolution exists for.

null (Sequence) -- everything else: routine developments, quotes, side
facts, anything that is not the story's setup or one of its settled
(or explicitly still-open) outcomes.

You will receive every claim from one source, each with a claim_id,
statement, claim_type, confidence, and date_anchor if any. Return a
`section` for every claim_id you were given -- exactly once each, no
more, no fewer, and no claim_id not in the input. Do not invent facts
or reorder; you are classifying, not composing.
"""


class _TaggedClaimModel(BaseModel):
    claim_id: int
    section: str | None


class _TaggingResponseModel(BaseModel):
    tags: list[_TaggedClaimModel]


def _normalize_section(source_id: int, raw: str | None) -> str | None:
    if raw is None:
        return None
    normalized = raw.strip().upper()
    if normalized in ("GROUND", "RESOLUTION"):
        return normalized
    if normalized in ("NULL", "NONE", "SEQUENCE", ""):
        return None
    raise SectionTaggingProviderError(
        f"source {source_id}: unrecognized section value from model: {raw!r}"
    )


def _build_contents(claims: list[ClaimForTagging]) -> str:
    lines = ["Claims from one source, in order:"]
    for c in claims:
        date_part = f", date_anchor={c.date_anchor}" if c.date_anchor else ""
        lines.append(
            f'- claim_id={c.claim_id}, claim_type={c.claim_type}, '
            f'confidence={c.confidence}{date_part}: "{c.statement}"'
        )
    return "\n".join(lines)


class GeminiSectionTaggingProvider:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model

    async def tag_source_claims(
        self, source_id: int, claims: list[ClaimForTagging]
    ) -> list[TaggedClaim]:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=_build_contents(claims),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_TaggingResponseModel,
                max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
            ),
        )
        parsed = response.parsed
        if not isinstance(parsed, _TaggingResponseModel):
            raise SectionTaggingProviderError(
                f"source {source_id}: response did not parse against the tagging schema"
            )

        expected_ids = {c.claim_id for c in claims}
        got_ids = {t.claim_id for t in parsed.tags}
        if got_ids != expected_ids or len(parsed.tags) != len(claims):
            raise MismatchedClaimIdsError(source_id, expected_ids, got_ids)

        tagged = [
            TaggedClaim(claim_id=t.claim_id, section=_normalize_section(source_id, t.section))
            for t in parsed.tags
        ]

        ground_ids = [t.claim_id for t in tagged if t.section == "GROUND"]
        if len(ground_ids) > 1:
            raise TooManyGroundClaimsError(source_id, ground_ids)

        return tagged
