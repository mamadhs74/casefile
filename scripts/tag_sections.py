"""Automatic Section (GROUND/RESOLUTION/NULL) tagging -- replaces the
hand-read pass docs/HANDOFF.md finding #43 describes. See
packages/script/section_tagging.py for the actual tagging/caching
orchestration; this script is the CLI entry point.

Tier 2 (write mode only): writes Claim.section to data/casefile.db
through the ORM. --verify mode writes nothing anywhere except its own
JSON cache under data/tagging_cache/.

QUOTA: at most one Gemini call per source not yet cached (0-N per run,
never a fixed number -- see packages.script.section_tagging's own
docstring on why sources, not the whole subject, are the call unit).
No retry of a failing call; a provider failure stops the script,
leaving every already-succeeded source cached for next time.

--verify: computes tags (same cache mechanism, same Gemini calls) and
prints them next to the subject's CURRENT Claim.section values -- a
diff, not a write. Nothing is persisted to data/casefile.db in this
mode, regardless of how many sources needed a real Gemini call to
compute the comparison.

Without --verify: writes tags through the ORM
(packages.script.section_tagging.apply_tags_to_db) and commits.

Usage:
    uv run python -m scripts.tag_sections --subject-id 10 --verify
    uv run python -m scripts.tag_sections --subject-id 10
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from packages.db.models import Claim
from packages.db.session import get_session
from packages.script.gemini_section_tagging_provider import GeminiSectionTaggingProvider
from packages.script.section_tagging import apply_tags_to_db, claims_by_source, compute_subject_tags

CACHE_DIR = Path("data/tagging_cache")


def _report_diff(grouped: dict[int, list[Claim]], tags: dict[int, dict[int, str | None]]) -> None:
    print()
    print(f"{'claim_id':>8}  {'source':>6}  {'hand tag':<11}  {'llm tag':<11}  match?")
    mismatches = 0
    total = 0
    for source_id, claims in sorted(grouped.items()):
        for claim in claims:
            assert claim.id is not None
            hand = claim.section.value.upper() if claim.section else "NULL"
            llm_raw = tags.get(source_id, {}).get(claim.id)
            llm = llm_raw if llm_raw else "NULL"
            match = "yes" if hand == llm else "NO"
            if hand != llm:
                mismatches += 1
            total += 1
            print(f"{claim.id:>8}  {source_id:>6}  {hand:<11}  {llm:<11}  {match}")
    print()
    print(f"{total - mismatches}/{total} match, {mismatches} mismatch(es)")


async def _run(subject_id: int, verify: bool) -> int:
    load_dotenv()
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    provider = GeminiSectionTaggingProvider(api_key)
    cache_path = CACHE_DIR / f"subject_{subject_id}.json"
    print(f"cache: {cache_path}")

    with get_session() as session:
        grouped = claims_by_source(session, subject_id)
        total_claims = sum(len(c) for c in grouped.values())
        print(f"subject {subject_id}: {len(grouped)} source(s), {total_claims} claim(s)")

        try:
            tags = await compute_subject_tags(grouped, provider, cache_path)
        except Exception as exc:  # noqa: BLE001  -- report and stop, no retry, see module docstring
            print(f"tagging failed, stopping (no retry): {exc!r}", file=sys.stderr)
            return 1

        if verify:
            _report_diff(grouped, tags)
            print()
            print("VERIFY MODE -- nothing written to data/casefile.db.")
            return 0

        changed = apply_tags_to_db(session, grouped, tags)
        session.commit()
        print(f"committed: {changed} claim(s) changed")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject-id", type=int, required=True)
    parser.add_argument("--verify", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args.subject_id, args.verify))


if __name__ == "__main__":
    sys.exit(main())
