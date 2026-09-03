"""Run `compose_episode` against the real Gemini API for any real
Episode -- generalizes scripts/compose_subject10_episode.py (kept, not
deleted, per the task this was built under) to take --episode-id
instead of a hardcoded subject-10-specific constant.

RESUMABLE: each section's successful composition is cached to a JSON
file on disk, keyed by section name, under outputs/<episode_id>/ (was
data/renders/episode1/ in the subject-10-specific script). On startup,
the cache is loaded and any section already present in it is served
from the cache -- Gemini is only called for sections not yet cached.
This exists because compose_episode itself stops at the first failing
call (chronological_composition.py's own fixed order: Sequence, Return,
Ground, Resolution) -- a 503 partway through used to mean every
already-succeeded call in that run was thrown away and re-requested
next time. Now it isn't: a section written to the cache survives across
runs, so a 503 on (say) Resolution after Sequence/Return/Ground already
succeeded means the next run makes exactly one call, not four.

QUOTA: at most one Gemini call per NOT-YET-CACHED section (0-4 per run,
not a fixed 4). Still no retry of a failing call within one run -- a
provider failure stops the script and reports the error, rather than
silently re-calling. This does not disable GeminiCompositionProvider's
own per-call truncation retry (a different failure mode, unrelated to
503s).

Does not change chronological_composition.py's compose_episode at all
-- CachingCompositionProvider wraps the real GeminiCompositionProvider
behind the same CompositionProvider protocol compose_episode already
depends on, so compose_episode has no idea a cache exists. Unchanged
from scripts/compose_subject10_episode.py.

min_claim_count is no longer a hardcoded constant (11, subject 10's
specific pool size) -- it's the real EpisodeClaim row count for
--episode-id, queried directly, so this works for a pool of any size
without editing a constant per episode.

SCOPE: compose_episode itself writes nothing to data/casefile.db --
confirmed by inspection of packages/script/chronological_composition.py,
it only reads (via generate_script) and returns a SectionedScript. This
script still doesn't touch the DB either; the cache is a plain JSON
file. Once compose_episode returns successfully (which, given caching,
only happens once every needed section is cached), the composed text
is also written to composed_script.json in the same output directory.

run_compose() is importable -- scripts/run_episode.py (Task 4) calls it
directly with an explicit output_dir (outputs/<run_id>/, not
outputs/<episode_id>/) rather than shelling out to this file.

Usage:
    uv run python -m scripts.compose_episode --episode-id 1
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from sqlmodel import Session, col, func, select

from packages.db.models import EpisodeClaim
from packages.db.session import get_session
from packages.script.chronological import SectionedScript, generate_script
from packages.script.chronological_composition import compose_episode
from packages.script.composition_provider import (
    ClaimForComposition,
    ComposedSection,
    CompositionProvider,
)
from packages.script.gemini_composition_provider import GeminiCompositionProvider
from packages.script.groq_composition_provider import GroqCompositionProvider


class CachingCompositionProvider:
    """Wraps a real CompositionProvider with an on-disk JSON cache,
    keyed by section name -- unchanged from
    scripts/compose_subject10_episode.py. section_sequence must match
    compose_episode's own call order exactly, since that's the only way
    this wrapper knows which cache key a given compose_section() call
    corresponds to; compose_episode itself passes no name."""

    def __init__(
        self,
        real: CompositionProvider,
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
            print(f"  [{section_name}] cache hit, skipping provider call")
            return ComposedSection(text=self._cache[section_name])

        print(f"  [{section_name}] not cached, calling provider...")
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


def _write_output(episode_id: int, output_path: Path, script: SectionedScript) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "episode_id": episode_id,
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
    output_path.write_text(json.dumps(payload, indent=2))
    print(f"composed text written to {output_path}")


def _episode_claim_count(session: Session, episode_id: int) -> int:
    query = select(func.count()).select_from(EpisodeClaim).where(
        col(EpisodeClaim.episode_id) == episode_id
    )
    return session.exec(query).one()


async def run_compose(episode_id: int, output_dir: Path, api_key: str) -> SectionedScript:
    """Importable entry point -- scripts/run_episode.py (Task 4) calls
    this directly with its own output_dir (outputs/<run_id>/) instead
    of shelling out to main(). Raises on failure (no retry); caller
    decides how to report/record that."""
    cache_path = output_dir / "compose_cache.json"
    output_path = output_dir / "composed_script.json"

    with get_session() as session:
        min_claim_count = _episode_claim_count(session, episode_id)
        print(f"episode {episode_id}: {min_claim_count} EpisodeClaim row(s)")

        # Read-only, same call compose_episode makes internally -- run
        # here too, purely to know the section order/names for the
        # cache, not to change or duplicate any write.
        allocated = generate_script(session, episode_id, min_claim_count=min_claim_count)
        sequence = _section_sequence(allocated)
        print(f"section sequence: {sequence}")
        cached_before = set(_load_cache(cache_path))
        print(f"already cached: {sorted(cached_before) or '(none)'}")

        real_provider = GeminiCompositionProvider(api_key)
        provider = CachingCompositionProvider(real_provider, cache_path, sequence)

        try:
            script = await compose_episode(
                session, episode_id, provider, min_claim_count=min_claim_count
            )
        except Exception:
            cached_after = set(_load_cache(cache_path))
            newly_cached = cached_after - cached_before
            print(
                f"newly cached this run: {sorted(newly_cached) or '(none)'}\n"
                f"cached overall: {sorted(cached_after)}",
                file=sys.stderr,
            )
            raise

        _report(script)
        _write_output(episode_id, output_path, script)
    return script


async def run_compose_groq(
    episode_id: int, output_dir: Path, api_key: str, model: str
) -> SectionedScript:
    """Groq counterpart to run_compose() above -- same orchestration
    (session, generate_script, section sequence, CachingCompositionProvider,
    compose_episode, report, write output), but pointed at
    GroqCompositionProvider and, critically, a SEPARATE cache/output
    file pair (compose_cache.groq.json / composed_script.groq.json).
    This is what keeps a Groq run from ever reading, writing, or
    colliding with compose_cache.json / composed_script.json -- the
    Gemini files run_compose() above owns -- per the task this was
    built under: no shared cache between providers, no automatic
    failover, provider selected explicitly by the caller."""
    cache_path = output_dir / "compose_cache.groq.json"
    output_path = output_dir / "composed_script.groq.json"

    with get_session() as session:
        min_claim_count = _episode_claim_count(session, episode_id)
        print(f"episode {episode_id}: {min_claim_count} EpisodeClaim row(s)")

        allocated = generate_script(session, episode_id, min_claim_count=min_claim_count)
        sequence = _section_sequence(allocated)
        print(f"section sequence: {sequence}")
        cached_before = set(_load_cache(cache_path))
        print(f"already cached: {sorted(cached_before) or '(none)'}")

        real_provider: CompositionProvider = GroqCompositionProvider(api_key, model)
        provider = CachingCompositionProvider(real_provider, cache_path, sequence)

        try:
            script = await compose_episode(
                session, episode_id, provider, min_claim_count=min_claim_count
            )
        except Exception:
            cached_after = set(_load_cache(cache_path))
            newly_cached = cached_after - cached_before
            print(
                f"newly cached this run: {sorted(newly_cached) or '(none)'}\n"
                f"cached overall: {sorted(cached_after)}",
                file=sys.stderr,
            )
            raise

        _report(script)
        _write_output(episode_id, output_path, script)
    return script


async def _run(episode_id: int, provider: str) -> int:
    load_dotenv()
    output_dir = Path(f"outputs/{episode_id}")

    try:
        if provider == "gemini":
            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
                return 1
            await run_compose(episode_id, output_dir, api_key)
        elif provider == "groq":
            groq_api_key = os.environ.get("GROQ_API_KEY")
            if not groq_api_key:
                print("GROQ_API_KEY is not set (see .env.example).", file=sys.stderr)
                return 1
            groq_model = os.environ.get("GROQ_MODEL")
            if not groq_model:
                print("GROQ_MODEL is not set (see .env.example).", file=sys.stderr)
                return 1
            await run_compose_groq(episode_id, output_dir, groq_api_key, groq_model)
        else:
            print(f"unknown --provider {provider!r}", file=sys.stderr)
            return 1
    except Exception as exc:  # noqa: BLE001  -- report and stop, no retry, see module docstring
        print(f"composition failed, stopping (no retry): {exc!r}", file=sys.stderr)
        return 1
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-id", type=int, required=True)
    parser.add_argument(
        "--provider",
        choices=["gemini", "groq"],
        default="gemini",
        help="Composition provider to use. No automatic failover between "
        "providers -- this selects one explicitly, per-run.",
    )
    return parser.parse_args()


def main() -> int:
    import asyncio

    args = _parse_args()
    return asyncio.run(_run(args.episode_id, args.provider))


if __name__ == "__main__":
    sys.exit(main())
