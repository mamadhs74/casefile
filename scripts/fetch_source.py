"""Fetch one URL into one subject's sources -- a thin, permanent CLI over
SourceFetcher.fetch_source(). No tier logic: every source lands UNVERIFIED
or REFERENCE per packages/research/tiering.py, same as calling
fetch_source() directly. Promoting to Tier A is a deliberate, separate,
by-hand step -- see docs/SCHEMA.md's "Fetch layer" section.

Usage (module form -- see docs/SCHEMA.md on why `-m scripts.fetch_source`,
not a bare script path):
    uv run python -m scripts.fetch_source --subject-id 10 --url "https://example.com/article"
    uv run python -m scripts.fetch_source --subject-id 10 --url "https://example.com/article" \\
        --publisher "Example Times"
"""

from __future__ import annotations

import argparse
import asyncio
import sys

import httpx

from packages.db.session import get_session
from packages.research.boilerplate import LikelyBoilerplateError
from packages.research.extraction import EmptyExtractionError
from packages.research.fetch import (
    DuplicateSourceContentError,
    FetchFailedError,
    SourceFetcher,
    UnknownSubjectError,
    UnknownSubjectStrategyError,
)
from packages.research.robots import RobotsDisallowedError, RobotsUnreachableError
from packages.research.tiering import TierCBlockedDomainError

FETCH_ERRORS = (
    TierCBlockedDomainError,
    RobotsDisallowedError,
    RobotsUnreachableError,
    FetchFailedError,
    EmptyExtractionError,
    LikelyBoilerplateError,
    DuplicateSourceContentError,
    UnknownSubjectError,
    UnknownSubjectStrategyError,
)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject-id", type=int, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--publisher", default=None)
    args = parser.parse_args()

    async with httpx.AsyncClient() as client:
        fetcher = SourceFetcher(client)
        with get_session() as session:
            try:
                source = await fetcher.fetch_source(
                    session, args.subject_id, args.url, publisher=args.publisher
                )
            except FETCH_ERRORS as exc:
                print(f"fetch failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                return 1

            print(f"source {source.id}: {source.url}")
            print(f"  domain: {source.domain}")
            print(f"  tier: {source.tier.value}")
            print(f"  word_count: {source.word_count}")
            return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
