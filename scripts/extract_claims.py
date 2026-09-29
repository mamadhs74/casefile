"""Run claim extraction against a single Source, for validating the
pipeline before any wider rollout -- see docs/SCHEMA.md's claim-
extraction section.

Deliberately single-source, not a batch/queue runner: there is no job
queue wired up yet (packages.db.models.Job exists as a table, nothing
reads it), and the first real run against a real Gemini response is
exactly the point where something previously only tested against a fake
provider should be checked by a human before it touches more than one
row.

Usage (module form -- `packages` isn't importable when this file is run as
a bare script path, since this project isn't installed as a package; see
docs/SCHEMA.md):
    uv run python -m scripts.extract_claims --source-id 1 --dry-run
    uv run python -m scripts.extract_claims --source-id 1
    uv run python -m scripts.extract_claims --source-id 1 --force
    uv run python -m scripts.extract_claims --source-id 1 --dry-run --provider groq

--provider defaults to gemini. No automatic failover between providers
-- this selects one explicitly, per-run, same posture as
scripts/compose_episode.py's own --provider flag.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from packages.db.models import Source
from packages.db.session import get_session
from packages.research.claim_extraction import ClaimExtractionResult, extract_claims_for_source
from packages.research.gemini_provider import DEFAULT_MODEL, GeminiClaimExtractor
from packages.research.groq_provider import GroqClaimExtractor
from packages.research.llm_provider import ClaimExtractionProvider, ExtractionProviderError


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
        help="Re-extract even if this source already has linked claims. "
        "Adds a new batch alongside the existing ones -- never deletes or merges.",
    )
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--provider",
        choices=["gemini", "groq"],
        default="gemini",
        help="Extraction provider to use. No automatic failover between "
        "providers -- this selects one explicitly, per-run.",
    )
    args = parser.parse_args()

    provider: ClaimExtractionProvider
    if args.provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
            return 1
        model = args.model or DEFAULT_MODEL
        provider = GeminiClaimExtractor(api_key, model=model)
    else:
        groq_api_key = os.environ.get("GROQ_API_KEY")
        if not groq_api_key:
            print("GROQ_API_KEY is not set (see .env.example).", file=sys.stderr)
            return 1
        groq_model = args.model or os.environ.get("GROQ_MODEL")
        if not groq_model:
            print("GROQ_MODEL is not set (see .env.example).", file=sys.stderr)
            return 1
        provider = GroqClaimExtractor(groq_api_key, groq_model)

    with get_session() as session:
        source = session.get(Source, args.source_id)
        if source is None:
            print(f"no Source with id={args.source_id}", file=sys.stderr)
            return 1

        if args.dry_run:
            await _print_request_preview(provider, source)

        try:
            result = await extract_claims_for_source(
                session, source, provider, force=args.force, dry_run=args.dry_run
            )
        except ExtractionProviderError as exc:
            print(f"extraction failed for source {source.id}: {exc}", file=sys.stderr)
            return 1

        _report(result, dry_run=args.dry_run)
        return 0


async def _print_request_preview(
    provider: GeminiClaimExtractor | GroqClaimExtractor, source: Source
) -> None:
    source_text = Path(source.text_path).read_text(encoding="utf-8")
    preview = provider.preview_request(source_text, source.tier.value)

    print("=== request shape ===")
    print(f"system_instruction ({len(preview.system_instruction)} chars):")
    print(preview.system_instruction)
    print(f"\ncontents ({len(preview.contents)} chars):")
    print(preview.contents)

    # count_tokens is Gemini-specific (its own free count_tokens
    # endpoint) -- GroqClaimExtractor has no equivalent, same posture
    # as groq_composition_provider.py not implementing one either.
    if isinstance(provider, GeminiClaimExtractor):
        token_count = await provider.count_tokens(source_text, source.tier.value)
        print(
            f"\n=== token estimate (real, via count_tokens) ===\n{token_count} total input tokens\n"
        )


def _report(result: ClaimExtractionResult, dry_run: bool) -> None:
    if result.skipped_already_extracted:
        print(
            f"source {result.source_id} already has linked claims -- skipped "
            "(pass --force to add another batch)."
        )
        return

    verb = "would create" if dry_run else "created"
    print(f"{verb} {len(result.claims)} claim(s) for source {result.source_id}:")
    for claim in result.claims:
        print(f"  [{claim.claim_type.value}/{claim.confidence.value}] {claim.statement}")
        print(f"    quote ({claim.span_start}-{claim.span_end}): {claim.quoted_span!r}")

    if result.rejected:
        print(f"rejected {len(result.rejected)} candidate(s):")
        for r in result.rejected:
            print(f"  [{r.reason}] {r.assertion}")
            print(f"    attempted quote: {r.quoted_span!r}")

    if result.zero_claims_on_tier_a_source:
        print(
            "NOTE: this is a Tier A source and it produced zero claims -- "
            "worth a look, not necessarily wrong."
        )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
