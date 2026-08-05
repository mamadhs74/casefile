"""Run entity extraction against a single Source, for validating the
pipeline before any wider rollout -- see docs/SCHEMA.md's Entity
extraction section.

Deliberately single-source, not a batch/queue runner -- same reasoning as
scripts/extract_claims.py: no job queue is wired up yet, and a first real
run against a real Gemini response is exactly the point where something
previously only tested against a fake provider should be checked by a
human before it touches more than one row.

Sources must be processed in order for a given subject -- entity
extraction's known-entity context only reflects sources already
processed (see docs/SCHEMA.md's order-dependence note), so running this
out of order changes what the pass can produce. This script does not
enforce an ordering itself; that's on the operator, same as claim
extraction leaves force/order decisions to the operator.

Usage (module form -- `packages` isn't importable when this file is run as
a bare script path, since this project isn't installed as a package; see
docs/SCHEMA.md):
    uv run python -m scripts.extract_entities --source-id 1 --dry-run
    uv run python -m scripts.extract_entities --source-id 1
    uv run python -m scripts.extract_entities --source-id 1 --force
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session

from packages.db.models import Source
from packages.db.session import get_session
from packages.research.entity_extraction import (
    EntityExtractionResult,
    extract_entities_for_source,
    known_entities_for_subject,
)
from packages.research.entity_provider import EntityExtractionProviderError
from packages.research.gemini_entity_provider import DEFAULT_MODEL, GeminiEntityExtractor


async def main() -> int:
    load_dotenv()  # .env is not loaded automatically anywhere else yet

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", type=int, required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run extraction and validation but persist nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if this source already has linked entity matches. "
        "Adds a new batch alongside the existing ones -- never deletes or merges.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    with get_session() as session:
        source = session.get(Source, args.source_id)
        if source is None:
            print(f"no Source with id={args.source_id}", file=sys.stderr)
            return 1

        provider = GeminiEntityExtractor(api_key, model=args.model)

        if args.dry_run:
            await _print_request_preview(provider, source, session)

        try:
            result = await extract_entities_for_source(
                session, source, provider, force=args.force, dry_run=args.dry_run
            )
        except EntityExtractionProviderError as exc:
            print(f"extraction failed for source {source.id}: {exc}", file=sys.stderr)
            return 1

        _report(result, dry_run=args.dry_run)
        return 0


async def _print_request_preview(
    provider: GeminiEntityExtractor, source: Source, session: Session
) -> None:
    source_text = Path(source.text_path).read_text(encoding="utf-8")
    known_entities = known_entities_for_subject(session, source.subject_id)
    preview = provider.preview_request(source_text, known_entities)
    token_count = await provider.count_tokens(source_text, known_entities)

    print("=== request shape ===")
    print(f"system_instruction ({len(preview.system_instruction)} chars):")
    print(preview.system_instruction)
    print(f"\ncontents ({len(preview.contents)} chars):")
    print(preview.contents)
    print(f"\n=== token estimate (real, via count_tokens) ===\n{token_count} total input tokens\n")


def _report(result: EntityExtractionResult, dry_run: bool) -> None:
    if result.skipped_already_extracted:
        print(
            f"source {result.source_id} already has linked entity matches -- skipped "
            "(pass --force to add another batch)."
        )
        return

    verb = "would create" if dry_run else "created"
    print(f"{verb} {len(result.entities)} entity mention(s) for source {result.source_id}:")
    for entity in result.entities:
        kind = "new" if entity.is_new else f"matched existing entity {entity.matched_entity_id}"
        print(f"  [{entity.role.value}/{kind}] {entity.name}")
        print(f"    span ({entity.span_start}-{entity.span_end}): {entity.identifying_span!r}")
        if entity.match_rationale:
            print(f"    rationale: {entity.match_rationale}")

    if result.rejected:
        print(f"rejected {len(result.rejected)} candidate(s):")
        for r in result.rejected:
            print(f"  [{r.reason}] {r.name}")
            print(f"    attempted span: {r.identifying_span!r}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
