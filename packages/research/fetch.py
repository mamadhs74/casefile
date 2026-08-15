"""Fetch layer: retrieves a URL and persists a Source row.

Order matters and is deliberate:

1. Tier C blocklist check -- before any network request at all, including
   robots.txt. docs/SOURCING.md: Tier C sources are "never read, never
   ingested," not merely excluded after the fact.
2. Idempotent (subject_id, url) check -- an operator re-fetching a URL they
   already have for this subject gets the existing row back, not a wasted
   network round trip.
3. robots.txt, then rate limiting, then the actual HTTP GET.
4. Extraction (packages/research/extraction.py) -- raises EmptyExtractionError
   before anything is persisted if the result is empty or near-empty. This
   ordering is load-bearing, not incidental: without it, two failed
   extractions (e.g. two different court-record scans with no text layer)
   would both hash to sha256("") and collide against Source's
   UniqueConstraint(subject_id, text_sha256) for the wrong reason --
   "identical empty content" rather than "identical real content."
5. Domain-reference-sample check (packages/research/boilerplate.py) --
   extracted text matching this domain's own root page, or any
   already-fetched Source from the same domain regardless of subject,
   is templated chrome that survived extraction looking like content, not
   a real duplicate. See docs/SCHEMA.md's "Extraction specificity" section
   for why this exists: a single such page, fetched once, would otherwise
   silently enter the corpus as a valid-looking Source and count toward
   R1's gate -- word count and the Tier C/dedup checks below do not catch
   it, because it isn't empty and it isn't a duplicate of anything in this
   subject's own sources.
6. Content-hash dedup check, scoped to this subject -- a syndicated copy
   of the same article under a second URL is not a new, independent
   source; see Source's own docstring in packages/db/models.py for why
   this matters to R1's gate.
7. Tier assignment -- packages/research/tiering.py, per-strategy since
   that module's own strategy-registration change (see its docstring).
   When the caller doesn't override tier explicitly, this now resolves
   the subject's own strategy first (Subject -> Strategy, both by id),
   which this fetcher previously never needed to look up at all -- see
   UnknownSubjectError / UnknownSubjectStrategyError below.
8. Write extracted text to disk, then persist the Source row.

Async throughout (matching docs/ARCHIVE-SPEC.md's established pattern for
the sibling archive-retrieval package) but not wired into a job queue --
packages.db.models.Job exists as a table; no worker process reads it yet,
so this is a plain awaitable a future job runner (or anything else) can
call directly.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlmodel import Session, select

from packages.db.models import Source, Strategy, Subject
from packages.domain.enums import SourceTier
from packages.domain.urls import derive_domain
from packages.research.boilerplate import DomainSampleCache, LikelyBoilerplateError
from packages.research.extraction import extract
from packages.research.rate_limit import DEFAULT_MIN_INTERVAL_S, DomainRateLimiter
from packages.research.robots import RobotsCache
from packages.research.tiering import assign_initial_tier, check_not_tier_c

# ARCHIVE-SPEC.md: "a descriptive User-Agent including a contact URL" --
# generic default, meant to be overridden with a real contact URL before
# fetching anything at scale. Not read from an environment variable: it's
# constructor-injected like everything else here, so a caller can't forget
# to set it and get a silently generic identity.
DEFAULT_USER_AGENT = "casefile-research-bot/1.0"

DEFAULT_TEXT_ROOT = Path("data/cases")
DEFAULT_TIMEOUT_S = 30.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE_S = 1.0


class FetchFailedError(Exception):
    """The HTTP request ultimately failed, after retries where applicable
    (429/5xx are retried with backoff; other 4xx are not, per
    docs/ARCHIVE-SPEC.md's established pattern)."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"failed to fetch {url!r}: {reason}")


class DuplicateSourceContentError(Exception):
    """The extracted text is byte-identical to an existing Source for this
    subject, under a different URL -- e.g. a syndicated copy. Not silently
    deduped: returning an unrelated existing row for a URL the caller
    explicitly asked to fetch would be a more surprising outcome than
    raising. See Source's docstring in packages/db/models.py for why this
    is enforced at all -- it's not duplicate-waste, it's R1's gate passing
    when it shouldn't."""

    def __init__(self, url: str, existing_source_id: int | None, existing_url: str) -> None:
        self.url = url
        self.existing_source_id = existing_source_id
        self.existing_url = existing_url
        super().__init__(
            f"{url!r} has the same extracted content as existing source "
            f"{existing_source_id} ({existing_url!r})"
        )


class UnknownSubjectError(Exception):
    """subject_id does not identify a real Subject. Only reachable via the
    auto-tier path (tier=None): assign_initial_tier now needs the
    subject's strategy, which this fetcher previously never had to look
    up at all. FK enforcement is off project-wide (see Episode.
    cold_open_claim_id's own docstring in packages/db/models.py), so a
    bad subject_id previously reached session.commit() and either failed
    there or silently wrote an orphaned Source; this raises earlier and
    more clearly instead."""

    def __init__(self, subject_id: int) -> None:
        self.subject_id = subject_id
        super().__init__(f"unknown subject: {subject_id!r}")


class UnknownSubjectStrategyError(Exception):
    """subject.strategy_id does not identify a real Strategy -- the same
    kind of gap UnknownSubjectError covers, one join further out."""

    def __init__(self, subject_id: int, strategy_id: int) -> None:
        self.subject_id = subject_id
        self.strategy_id = strategy_id
        super().__init__(f"subject {subject_id!r} references unknown strategy {strategy_id!r}")


class SourceFetcher:
    """Holds the shared httpx.AsyncClient, robots.txt cache, rate limiter,
    and domain-reference-sample cache across multiple fetches -- an
    operator fetching a dozen URLs from one site should cost one
    robots.txt request and one reference-sample fetch, not re-derive
    either per call.

    Caller manages the DB session lifecycle (no owns_session default-
    session logic here, unlike packages/research/gate.py) -- a batch of
    fetches for one subject should share one session, not open and close
    one per URL.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        text_root: Path = DEFAULT_TEXT_ROOT,
        min_request_interval_s: float = DEFAULT_MIN_INTERVAL_S,
    ) -> None:
        self._client = client
        self._user_agent = user_agent
        self._text_root = text_root
        self._robots = RobotsCache(client, user_agent)
        self._rate_limiter = DomainRateLimiter(min_request_interval_s)
        self._domain_samples = DomainSampleCache()

    async def fetch_source(
        self,
        session: Session,
        subject_id: int,
        url: str,
        *,
        title: str | None = None,
        publisher: str | None = None,
        published_date: date | None = None,
        tier: SourceTier | None = None,
    ) -> Source:
        """title/publisher/published_date/tier are caller overrides; where
        omitted, title/publisher/published_date fall back to best-effort
        extraction metadata (frequently absent, especially for PDFs), and
        tier falls back to packages.research.tiering.assign_initial_tier(),
        resolved against this subject's own strategy. Whether that can
        ever return a Tier A value is now that strategy's own call, not a
        blanket rule this method enforces -- see that module's docstring.
        For every strategy that hasn't registered its own tier assigner,
        nothing changes: still never Tier A, still a deliberate human
        action after review to get there.
        """
        check_not_tier_c(url)

        existing_by_url = _find_by_url(session, subject_id, url)
        if existing_by_url is not None:
            return existing_by_url

        await self._robots.check(url)
        await self._rate_limiter.wait(url)

        response = await self._get_with_retry(url)
        content_type = response.headers.get("content-type", "")
        extracted = extract(url, response.content, content_type)
        text_sha256 = hashlib.sha256(extracted.text.encode()).hexdigest()
        domain = derive_domain(url)

        reference_hash = await self._get_domain_reference_hash(url)
        if reference_hash is not None and reference_hash == text_sha256:
            raise LikelyBoilerplateError(url, domain)

        domain_duplicate = _find_domain_wide_duplicate(session, domain, text_sha256)
        if domain_duplicate is not None:
            raise LikelyBoilerplateError(url, domain)

        duplicate = _find_by_hash(session, subject_id, text_sha256)
        if duplicate is not None:
            raise DuplicateSourceContentError(url, duplicate.id, duplicate.url)

        text_path = self._write_text(subject_id, text_sha256, extracted.text)

        if tier is not None:
            resolved_tier = tier
        else:
            strategy_slug = _resolve_strategy_slug(session, subject_id)
            resolved_tier = assign_initial_tier(url, strategy_slug)

        source = Source(
            subject_id=subject_id,
            url=url,
            publisher=publisher or extracted.publisher or "",
            title=title or extracted.title or "",
            published_date=published_date or extracted.published_date,
            retrieved_at=datetime.now(UTC),
            tier=resolved_tier,
            text_path=str(text_path),
            text_sha256=text_sha256,
            word_count=extracted.word_count,
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        return source

    async def _get_domain_reference_hash(self, url: str) -> str | None:
        """The domain root, not a sibling record page -- simpler to derive
        (no need to know another real URL on the site) and more likely to
        be pure chrome (a homepage is mostly navigation and teasers by
        construction). Fetched once per host and cached, same shape as
        RobotsCache. Any failure along the way (robots disallow, network
        error, the root's own extraction being empty) degrades to "no
        reference for this host" -- this check exists to improve
        confidence, it must never block the fetch it's checking."""
        host = urlsplit(url).netloc.lower()
        if self._domain_samples.has(host):
            return self._domain_samples.get(host)

        root_url = f"{urlsplit(url).scheme}://{host}/"
        sample_hash: str | None = None
        try:
            await self._robots.check(root_url)
            await self._rate_limiter.wait(root_url)
            response = await self._get_with_retry(root_url)
            content_type = response.headers.get("content-type", "")
            extracted = extract(root_url, response.content, content_type)
            sample_hash = hashlib.sha256(extracted.text.encode()).hexdigest()
        except Exception:
            sample_hash = None

        self._domain_samples.set(host, sample_hash)
        return sample_hash

    async def _get_with_retry(self, url: str) -> httpx.Response:
        for attempt in range(MAX_RETRIES):
            is_last_attempt = attempt == MAX_RETRIES - 1
            try:
                response = await self._client.get(
                    url,
                    timeout=DEFAULT_TIMEOUT_S,
                    headers={"User-Agent": self._user_agent},
                )
            except httpx.HTTPError as exc:
                if is_last_attempt:
                    raise FetchFailedError(url, str(exc)) from exc
                await asyncio.sleep(RETRY_BACKOFF_BASE_S * (2**attempt))
                continue

            if response.status_code == 429 or response.status_code >= 500:
                if is_last_attempt:
                    raise FetchFailedError(url, f"HTTP {response.status_code}")
                await asyncio.sleep(RETRY_BACKOFF_BASE_S * (2**attempt))
                continue

            if response.status_code >= 400:
                raise FetchFailedError(url, f"HTTP {response.status_code}")

            return response

        # Unreachable: MAX_RETRIES >= 1 guarantees the loop above always
        # returns or raises before exhausting iterations.
        raise FetchFailedError(url, "exhausted retries")

    def _write_text(self, subject_id: int, text_sha256: str, text: str) -> Path:
        directory = self._text_root / str(subject_id) / "sources"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{text_sha256}.txt"
        path.write_text(text, encoding="utf-8")
        return path


def _resolve_strategy_slug(session: Session, subject_id: int) -> str:
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise UnknownSubjectError(subject_id)

    strategy = session.get(Strategy, subject.strategy_id)
    if strategy is None:
        raise UnknownSubjectStrategyError(subject_id, subject.strategy_id)

    return strategy.slug


def _find_by_url(session: Session, subject_id: int, url: str) -> Source | None:
    return session.exec(
        select(Source).where(Source.subject_id == subject_id, Source.url == url)
    ).first()


def _find_by_hash(session: Session, subject_id: int, text_sha256: str) -> Source | None:
    return session.exec(
        select(Source).where(
            Source.subject_id == subject_id, Source.text_sha256 == text_sha256
        )
    ).first()


def _find_domain_wide_duplicate(session: Session, domain: str, text_sha256: str) -> Source | None:
    """Unscoped by subject, deliberately: the same template chrome can
    recur across different subjects fetching from the same domain, and the
    per-subject check in _find_by_hash would never see that -- it only
    ever looks within one subject's own sources."""
    return session.exec(
        select(Source).where(Source.domain == domain, Source.text_sha256 == text_sha256)
    ).first()
