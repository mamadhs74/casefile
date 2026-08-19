"""Run `compose_episode` against the real Gemini API for the real
Episode 1 (subject 10, the Paramount-Warner Bros. merger story) --
see scripts/create_subject10_episode.py, which created it.

QUOTA: up to 4 Gemini calls (Sequence, Return, Ground, Resolution --
same order as chronological_composition.py). No retry of the whole run
on purpose -- a provider failure on any section stops the script and
reports the error, rather than silently re-calling. This does not
disable GeminiCompositionProvider's own per-call truncation retry
(a different failure mode, unrelated to 503s).

SCOPE: compose_episode itself writes nothing to data/casefile.db --
confirmed by inspection of packages/script/chronological_composition.py,
it only reads (via generate_script) and returns a SectionedScript. This
script does not persist that result anywhere either; it only prints it.

Usage:
    uv run python -m scripts.compose_subject10_episode
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from packages.db.session import get_session
from packages.script.chronological import SectionedScript
from packages.script.chronological_composition import compose_episode
from packages.script.gemini_composition_provider import GeminiCompositionProvider

EPISODE_ID = 1
MIN_CLAIM_COUNT = 11


def _report(script: SectionedScript) -> None:
    sections: list[tuple[str, str, int, int]] = [
        ("Cold Open", script.cold_open, script.actual_word_counts.cold_open, script.budgeted_word_counts.cold_open),
        ("Thesis", script.thesis, script.actual_word_counts.thesis, script.budgeted_word_counts.thesis),
        ("Ground", script.ground, script.actual_word_counts.ground, script.budgeted_word_counts.ground),
        ("Sequence", script.sequence, script.actual_word_counts.sequence, script.budgeted_word_counts.sequence),
        ("Resolution", script.resolution, script.actual_word_counts.resolution, script.budgeted_word_counts.resolution),
        ("Return", script.return_, script.actual_word_counts.return_, script.budgeted_word_counts.return_),
    ]
    total_actual = 0
    for name, text, actual, budget in sections:
        pct = (actual / budget * 100) if budget else 0.0
        total_actual += actual
        print(f"=== {name} -- {actual} words actual / {budget} words budgeted ({pct:.0f}%) ===")
        print(text if text else "(empty)")
        print()
    print(f"TOTAL WORDS (actual): {total_actual}")
    print(f"derived_runtime_minutes: {script.derived_runtime_minutes}")


async def _run() -> int:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    provider = GeminiCompositionProvider(api_key)
    with get_session() as session:
        try:
            script = await compose_episode(session, EPISODE_ID, provider, min_claim_count=MIN_CLAIM_COUNT)
        except Exception as exc:  # noqa: BLE001  -- report and stop, no retry, see module docstring
            print(f"composition failed, stopping (no retry): {exc!r}", file=sys.stderr)
            return 1
        _report(script)
    return 0


def main() -> int:
    import asyncio

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
