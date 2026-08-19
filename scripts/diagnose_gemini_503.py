"""Diagnostic: is the free-tier Gemini model itself down, or is
compose_episode's specific request the problem? Two consecutive 503s
from scripts/compose_subject10_episode.py prompted this -- see
docs/HANDOFF.md.

Uses the exact same provider class and method compose_episode calls
(GeminiCompositionProvider.compose_section), so the request mechanics
(client construction, model name, system instruction, JSON response
schema) are identical. The only thing that changes is the content: one
trivial claim, unrelated to casefile or any real episode.

ONE call. No retry. Reports the raw exception (if it fails) or the raw
parsed response (if it succeeds) -- nothing else runs after.

Usage:
    uv run python -m scripts.diagnose_gemini_503
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

from packages.script.composition_provider import ClaimForComposition
from packages.script.gemini_composition_provider import GeminiCompositionProvider

# Deliberately unrelated to casefile/subject 10/any real episode.
_DIAGNOSTIC_CLAIM = ClaimForComposition(
    claim_id=0,
    statement="The Pacific Ocean is the largest ocean on Earth.",
    claim_type="fact",
    confidence="established",
    date_anchor=None,
    thesis_bearing=False,
    word_target=10,
)
_DIAGNOSTIC_THESIS = "This is a connectivity diagnostic, not a real episode."


async def main() -> int:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    provider = GeminiCompositionProvider(api_key)
    try:
        result = await provider.compose_section([_DIAGNOSTIC_CLAIM], _DIAGNOSTIC_THESIS, 10)
    except Exception as exc:  # noqa: BLE001  -- report and stop, no retry
        print(f"diagnostic call FAILED: {exc!r}", file=sys.stderr)
        return 1

    print("diagnostic call SUCCEEDED")
    print(f"raw response text: {result.text!r}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
