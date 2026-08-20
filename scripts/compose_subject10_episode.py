"""Run `compose_episode` against the real Gemini API for the real
Episode 1 (subject 10, the Paramount-Warner Bros. merger story) --
see scripts/create_subject10_episode.py, which created it.

RESUMABLE: each section's successful composition is cached to a JSON
file on disk (CACHE_PATH), keyed by section name. On startup, the cache
is loaded and any section already present in it is served from the
cache -- Gemini is only called for sections not yet cached. This exists
because compose_episode itself stops at the first failing call
(chronological_composition.py's own fixed order: Sequence, Return,
Ground, Resolution) -- a 503 partway through used to mean every already-
succeeded call in that run was thrown away and re-requested next time.
Now it isn't: a section written to the cache survives across runs, so a
503 on (say) Resolution after Sequence/Return/Ground already succeeded
means the next run makes exactly one call, not four.

QUOTA: at most one Gemini call per NOT-YET-CACHED section (so 0-4 per
run, not a fixed 4). Still no retry of a failing call within one run --
a provider failure stops the script and reports the error, rather than
silently re-calling. This does not disable GeminiCompositionProvider's
own per-call truncation retry (a different failure mode, unrelated to
503s).

Does not change chronological_composition.py's compose_episode at all
-- CachingCompositionProvider below wraps the real GeminiCompositionProvider
behind the same CompositionProvider protocol compose_episode already
depends on, so compose_episode has no idea a cache exists. Wrapping
happens entirely at this script's level, per the task this was built
under.

section_sequence (the order compose_episode will call the provider in,
and therefore which cache key each call corresponds to) is computed
once, up front, from generate_script's own allocation -- Sequence and
Return always, Ground/Resolution only when generate_script actually put
a claim there, mirroring chronological_composition.py's own
conditionals exactly. This is a read, not a write (see SCOPE below);
running it twice (once here, once again inside compose_episode itself)
costs nothing and touches no table.

SCOPE: compose_episode itself writes nothing to data/casefile.db --
confirmed by inspection of packages/script/chronological_composition.py,
it only reads (via generate_script) and returns a SectionedScript. This
script still doesn't touch the DB either; CACHE_PATH is a plain JSON
file, not a database row. Once compose_episode returns successfully
(which, given caching, only happens once every needed section is
cached), the composed text is also written to OUTPUT_PATH and reported.

Usage:
    uv run python -m scripts.compose_subject10_episode
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

from packages.db.session import get_session
from packages.script.chronological import SectionedScript, generate_script
from packages.script.chronological_composition import compose_episode
from packages.script.composition_provider import ClaimForComposition, ComposedSection
from packages.script.gemini_composition_provider import GeminiCompositionProvider

EPISODE_ID = 1
MIN_CLAIM_COUNT = 11

OUT_DIR = Path("data/renders/episode1")
CACHE_PATH = OUT_DIR / "compose_cache.json"
OUTPUT_PATH = OUT_DIR / "composed_script.json"


class CachingCompositionProvider:
    """Wraps a real CompositionProvider with an on-disk JSON cache,
    keyed by section name -- see module docstring. section_sequence
    must match compose_episode's own call order exactly, since that's
    the only way this wrapper knows which cache key a given
    compose_section() call corresponds to; compose_episode itself
    passes no name."""

    def __init__(
        self,
        real: GeminiCompositionProvider,
        cache_path: Path,
        section_sequence: list[str],
    ) -> None:
        self._real = real
        self._cache_path = cache_path
        self._section_sequence = list(section_sequence)
        self._call_index = 0
        self._cache: dict[str, str] = _load_cache(cache_path)

    async def compose_section(
        self, claims: list[ClaimForComposition], thesis: str, word_budget: int
    ) -> ComposedSection:
        section_name = self._section_sequence[self._call_index]
        self._call_index += 1

        if section_name in self._cache:
            print(f"  [{section_name}] cache hit, skipping Gemini call")
            return ComposedSection(text=self._cache[section_name])

        print(f"  [{section_name}] not cached, calling Gemini...")
        result = await self._real.compose_section(claims, thesis, word_budget)
        self._cache[section_name] = result.text
        _save_cache(self._cache_path, self._cache)
        print(f"  [{section_name}] succeeded, cached")
        return result


def _load_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return cast("dict[str, str]", json.loads(path.read_text()))


def _save_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2))


def _section_sequence(allocated: SectionedScript) -> list[str]:
    """Mirrors chronological_composition.py's compose_episode call
    order exactly: Sequence and Return always, Ground/Resolution only
    when generate_script's allocation put a claim there."""
    names = ["sequence", "return"]
    if allocated.ground_claims:
        names.append("ground")
    if allocated.resolution_claims:
        names.append("resolution")
    return names


def _report(script: SectionedScript) -> None:
    counts = script.actual_word_counts
    budgets = script.budgeted_word_counts
    sections: list[tuple[str, str, int, int]] = [
        ("Cold Open", script.cold_open, counts.cold_open, budgets.cold_open),
        ("Thesis", script.thesis, counts.thesis, budgets.thesis),
        ("Ground", script.ground, counts.ground, budgets.ground),
        ("Sequence", script.sequence, counts.sequence, budgets.sequence),
        ("Resolution", script.resolution, counts.resolution, budgets.resolution),
        ("Return", script.return_, counts.return_, budgets.return_),
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


def _write_output(script: SectionedScript) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "episode_id": EPISODE_ID,
        "cold_open": script.cold_open,
        "thesis": script.thesis,
        "ground": script.ground,
        "sequence": script.sequence,
        "resolution": script.resolution,
        "return_": script.return_,
        "actual_word_counts": {
            "cold_open": script.actual_word_counts.cold_open,
            "thesis": script.actual_word_counts.thesis,
            "ground": script.actual_word_counts.ground,
            "sequence": script.actual_word_counts.sequence,
            "resolution": script.actual_word_counts.resolution,
            "return_": script.actual_word_counts.return_,
        },
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))
    print(f"composed text written to {OUTPUT_PATH}")


async def _run() -> int:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    with get_session() as session:
        # Read-only, same call compose_episode makes internally -- run
        # here too, purely to know the section order/names for the
        # cache, not to change or duplicate any write.
        allocated = generate_script(session, EPISODE_ID, min_claim_count=MIN_CLAIM_COUNT)
        sequence = _section_sequence(allocated)
        print(f"section sequence: {sequence}")
        cached_before = set(_load_cache(CACHE_PATH))
        print(f"already cached: {sorted(cached_before) or '(none)'}")

        real_provider = GeminiCompositionProvider(api_key)
        provider = CachingCompositionProvider(real_provider, CACHE_PATH, sequence)

        try:
            script = await compose_episode(
                session, EPISODE_ID, provider, min_claim_count=MIN_CLAIM_COUNT
            )
        except Exception as exc:  # noqa: BLE001  -- report and stop, no retry, see module docstring
            cached_after = set(_load_cache(CACHE_PATH))
            newly_cached = cached_after - cached_before
            print(
                f"composition failed, stopping (no retry): {exc!r}\n"
                f"newly cached this run: {sorted(newly_cached) or '(none)'}\n"
                f"cached overall: {sorted(cached_after)}",
                file=sys.stderr,
            )
            return 1

        _report(script)
        _write_output(script)
    return 0


def main() -> int:
    import asyncio

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
