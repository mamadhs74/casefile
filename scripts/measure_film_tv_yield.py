"""Claim yield per trade-press story, for film-tv-news.

SCOPE: writes Source, Claim, and ClaimSource rows via the existing
packages/research path (SourceFetcher.fetch_source, then
extract_claims_for_source against the real Gemini claim provider) --
the same path scripts/fetch_source.py and scripts/extract_claims.py use
for criminal-cases. No Subject creation, no Episode creation, no schema
change, no migration.

QUOTA: claim extraction costs Gemini calls. At most 5 articles are ever
processed (one per required domain), so at most 5 extraction calls are
ever made; an explicit counter still guards against exceeding that if
the loop is ever changed. An article under PAYWALL_CHAR_THRESHOLD chars
is reported and skipped before any extraction call is attempted, so
quota is never spent on unusable text. No retries: a failed fetch or a
failed extraction is reported and the run moves on to the next article.

--subject-id: not asked for in the task this was built under, but
Source.subject_id is a required, non-nullable foreign key
(packages/db/models.py) -- fetch_source() cannot write a Source row
without one, and this script does not create a Subject (explicitly out
of scope). scripts/fetch_source.py already takes the same flag for the
same reason. As of this script being written, no Subject belongs to the
film-tv-news strategy yet (all 9 existing Subjects are criminal-cases) --
this script checks that the given --subject-id's strategy actually is
film-tv-news and fails clearly rather than silently measuring the wrong
strategy's gate against it. A real run needs a real film-tv-news Subject
to exist first.

Deduplication reuses scripts/measure_claim_duplication.py's own
clustering (ClaimText, _cluster, DEFAULT_THRESHOLD) rather than
reimplementing it, applied separately per article, per the task.

Usage (module form -- `packages` isn't importable when this file is run as
a bare script path, since this project isn't installed as a package; see
docs/SCHEMA.md):
    uv run python -m scripts.measure_film_tv_yield --subject-id 10 \\
        "<variety.com URL>" "<hollywoodreporter.com URL>" "<deadline.com URL>" \\
        "<thewrap.com URL>" "<indiewire.com URL>"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

import httpx
from dotenv import load_dotenv
from sqlmodel import Session

from packages.db.models import Strategy, Subject
from packages.db.session import get_session
from packages.domain.urls import derive_domain
from packages.research.claim_extraction import ExtractedClaim, extract_claims_for_source
from packages.research.fetch import SourceFetcher
from packages.research.gate import check_source_gate
from packages.research.gemini_provider import GeminiClaimExtractor
from packages.research.llm_provider import ExtractionProviderError
from packages.script.chronological import WORDS_PER_CLAIM
from packages.strategies.film_tv_news import SLUG as FILM_TV_NEWS_SLUG
from packages.visual.timing import NARRATION_WPM
from scripts.fetch_source import FETCH_ERRORS
from scripts.measure_claim_duplication import DEFAULT_THRESHOLD, ClaimText, _cluster
from scripts.render_scratch_visual import _format_mmss

REQUIRED_DOMAINS: tuple[str, ...] = (
    "variety.com",
    "hollywoodreporter.com",
    "deadline.com",
    "thewrap.com",
    "indiewire.com",
)

PAYWALL_CHAR_THRESHOLD = 500
MAX_EXTRACTION_CALLS = 5


@dataclass
class ArticleResult:
    domain: str
    url: str
    fetched: bool = False
    char_count: int = 0
    raw_claims: list[ExtractedClaim] = field(default_factory=list)
    note: str | None = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--subject-id",
        type=int,
        required=True,
        help="An existing Subject belonging to the film-tv-news strategy.",
    )
    parser.add_argument("variety_url", help="A variety.com article URL.")
    parser.add_argument("hollywoodreporter_url", help="A hollywoodreporter.com article URL.")
    parser.add_argument("deadline_url", help="A deadline.com article URL.")
    parser.add_argument("thewrap_url", help="A thewrap.com article URL.")
    parser.add_argument("indiewire_url", help="An indiewire.com article URL.")
    return parser.parse_args()


def _check_subject(session: Session, subject_id: int) -> str | None:
    """Returns an error message if --subject-id doesn't identify a real
    film-tv-news Subject, else None."""
    subject = session.get(Subject, subject_id)
    if subject is None:
        return f"no Subject with id={subject_id}"

    strategy = session.get(Strategy, subject.strategy_id)
    strategy_label = strategy.slug if strategy is not None else repr(subject.strategy_id)
    if strategy is None or strategy.slug != FILM_TV_NEWS_SLUG:
        return (
            f"subject {subject_id} belongs to strategy {strategy_label}, not "
            f"{FILM_TV_NEWS_SLUG!r} -- check_source_gate would measure the wrong "
            "strategy's thresholds against these sources"
        )
    return None


async def _process_articles(
    session: Session,
    fetcher: SourceFetcher,
    claim_provider: GeminiClaimExtractor,
    subject_id: int,
    urls: list[str],
) -> list[ArticleResult]:
    results: list[ArticleResult] = []
    extraction_calls_made = 0

    for expected_domain, url in zip(REQUIRED_DOMAINS, urls, strict=True):
        print(f"=== {expected_domain} ===")
        print(f"  url: {url}")

        actual_domain = derive_domain(url)
        if actual_domain != expected_domain:
            print(f"  SKIPPED: resolves to domain {actual_domain!r}, expected {expected_domain!r}")
            results.append(ArticleResult(expected_domain, url, note="domain_mismatch"))
            continue

        try:
            source = await fetcher.fetch_source(session, subject_id, url)
        except FETCH_ERRORS as exc:
            print(f"  FETCH FAILED: {type(exc).__name__}: {exc}")
            results.append(ArticleResult(actual_domain, url, note="fetch_failed"))
            continue

        source_text = Path(source.text_path).read_text(encoding="utf-8")
        char_count = len(source_text)
        print(f"  chars: {char_count}")

        fetched = partial(ArticleResult, actual_domain, url, fetched=True, char_count=char_count)

        if char_count < PAYWALL_CHAR_THRESHOLD:
            print(
                f"  PAYWALL/EXTRACTION FAILURE WARNING: {char_count} chars < "
                f"{PAYWALL_CHAR_THRESHOLD} -- skipping extraction call"
            )
            results.append(fetched(note="under_threshold"))
            continue

        if extraction_calls_made >= MAX_EXTRACTION_CALLS:
            print(f"  SKIPPED: would exceed {MAX_EXTRACTION_CALLS} extraction calls this run")
            results.append(fetched(note="quota_guard"))
            continue

        try:
            extraction = await extract_claims_for_source(session, source, claim_provider)
        except ExtractionProviderError as exc:
            print(f"  EXTRACTION FAILED: {exc}")
            results.append(fetched(note="extraction_failed"))
            continue
        extraction_calls_made += 1

        if extraction.skipped_already_extracted:
            print("  NOTE: source already had linked claims -- 0 new claims, no quota spent")
            results.append(fetched(note="already_extracted"))
            continue

        print(f"  raw claims: {len(extraction.claims)}")
        results.append(fetched(raw_claims=extraction.claims))

    return results


def _pick_representative_id(claim_ids: list[int], by_id: dict[int, ExtractedClaim]) -> int:
    """Longest statement wins, tie-broken by lowest claim_id -- same rule
    scripts/dedupe_scratch_borden.py uses."""
    return min(claim_ids, key=lambda cid: (-len(by_id[cid].statement), cid))


def _print_summary(subject_id: int, articles: list[ArticleResult]) -> None:
    print()
    print("=== yield summary ===")

    raw_total = 0
    distinct_total = 0
    representatives: list[tuple[str, ExtractedClaim]] = []

    for article in articles:
        by_id = {c.claim_id: c for c in article.raw_claims if c.claim_id is not None}
        raw_count = len(by_id)
        distinct_count = 0

        if by_id:
            claim_texts = [
                ClaimText(claim_id=cid, subject_id=subject_id, statement=claim.statement)
                for cid, claim in by_id.items()
            ]
            _, clusters = _cluster(claim_texts, DEFAULT_THRESHOLD)
            distinct_count = len(clusters)
            for members in clusters.values():
                rep_id = _pick_representative_id(members, by_id)
                representatives.append((article.domain, by_id[rep_id]))

        raw_total += raw_count
        distinct_total += distinct_count
        note = f"  ({article.note})" if article.note else ""
        print(f"  {article.domain:<24} raw={raw_count:<4} distinct={distinct_count:<4}{note}")

    print(f"  {'TOTAL':<24} raw={raw_total:<4} distinct={distinct_total:<4}")

    dup_rate = (raw_total - distinct_total) / raw_total * 100 if raw_total else 0.0
    print(f"duplication rate: {dup_rate:.1f}%")

    word_budget = distinct_total * WORDS_PER_CLAIM
    print(f"word budget at {WORDS_PER_CLAIM} words/claim: {word_budget}")

    runtime_seconds = word_budget / NARRATION_WPM * 60
    runtime_mmss = _format_mmss(runtime_seconds)
    print(f"runtime at {NARRATION_WPM} wpm: {runtime_seconds:.1f}s ({runtime_mmss})")

    fetched_domains = {a.domain for a in articles if a.fetched}
    print(f"distinct source domains fetched: {len(fetched_domains)}")

    print()
    print("ten longest distinct claims across all five articles:")
    longest = sorted(representatives, key=lambda pair: len(pair[1].statement), reverse=True)[:10]
    if not longest:
        print("  none")
    for domain, claim in longest:
        print(f"  [{domain}] {claim.statement}")


def _print_gate(subject_id: int, session: Session) -> None:
    print()
    print(f"=== R1 source-diversity gate ({FILM_TV_NEWS_SLUG}) ===")
    result = check_source_gate(subject_id, session)
    print(f"verdict: {'PASS' if result.passed else 'FAIL'}")
    print(f"  verified_source_count:  {result.verified_source_count}")
    print(f"  tier_a_source_count:    {result.tier_a_source_count}")
    print(f"  distinct_domain_count:  {result.distinct_domain_count}")
    for reason in result.reasons:
        print(f"  reason: {reason.value}")


async def main() -> int:
    load_dotenv()  # .env is not loaded automatically anywhere else yet
    args = _parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set (see .env.example).", file=sys.stderr)
        return 1

    urls = [
        args.variety_url,
        args.hollywoodreporter_url,
        args.deadline_url,
        args.thewrap_url,
        args.indiewire_url,
    ]

    async with httpx.AsyncClient(follow_redirects=True) as client:
        fetcher = SourceFetcher(client)
        claim_provider = GeminiClaimExtractor(api_key)

        with get_session() as session:
            error = _check_subject(session, args.subject_id)
            if error is not None:
                print(error, file=sys.stderr)
                return 1

            articles = await _process_articles(
                session, fetcher, claim_provider, args.subject_id, urls
            )
            _print_gate(args.subject_id, session)

    _print_summary(args.subject_id, articles)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
