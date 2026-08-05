"""packages/research/fetch.py end to end, against a mocked transport -- no
real network, matching docs/ARCHIVE-SPEC.md's testing guidance.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from sqlmodel import Session, select

from packages.db.models import Source
from packages.domain.enums import SourceTier
from packages.research.boilerplate import LikelyBoilerplateError
from packages.research.extraction import EmptyExtractionError
from packages.research.fetch import DuplicateSourceContentError, SourceFetcher
from packages.research.robots import RobotsDisallowedError
from packages.research.tiering import TierCBlockedDomainError
from tests.factories import make_subject

ARTICLE_HTML = """
<html>
<head><title>Six Vanish From Bavarian Farmstead</title></head>
<body>
<article>
<p>In March 1922, six people vanished from a small farmstead in Bavaria.
Andreas Gruber, his wife, their widowed daughter, and her four children had
not been seen for several days when a neighbor grew concerned and went to
check on them. Investigators later determined the family had been killed.</p>
</article>
</body>
</html>
"""

ARTICLE_HTML_TWO = """
<html>
<head><title>Vessel Overdue on Southampton Crossing</title></head>
<body>
<article>
<p>The Board of Trade opened an inquiry Monday into the disappearance of a
passenger liner bound for Southampton, last sighted eleven days ago. Family
members of the crew have gathered at the port awaiting further word from
officials conducting the search.</p>
</article>
</body>
</html>
"""

THIN_HTML = "<html><head><title>x</title></head><body><p>Too short.</p></body></html>"

# A 200 response whose body is a generic, well-formed "something went
# wrong" page -- structurally indistinguishable from a real short article
# (a heading plus a prose paragraph inside a semantic content container),
# so favor_precision=True does not catch it. Well above
# MIN_EXTRACTED_WORD_COUNT (40), so the word-count floor doesn't catch it
# either. This is exactly the failure mode the domain-reference-sample
# check exists for -- see docs/SCHEMA.md's "Extraction specificity"
# section.
GENERIC_ERROR_PAGE = """
<html><head><title>Service Temporarily Unavailable</title></head>
<body>
<nav><a href="/">Home</a> <a href="/help">Help</a></nav>
<main>
<h1>Service Temporarily Unavailable</h1>
<p>We're sorry, but the page you requested could not be loaded at this time.
Our team has been automatically notified and is working to resolve the issue
as quickly as possible. This is usually a temporary problem caused by high
traffic or scheduled maintenance. Please try refreshing the page in a few
minutes, or contact support if the problem persists beyond one hour.</p>
</main>
</body></html>
"""


def _persist_subject(session: Session, strategy_id: int, **overrides: object) -> int:
    subject = make_subject(strategy_id, **overrides)
    session.add(subject)
    session.commit()
    session.refresh(subject)
    assert subject.id is not None
    return subject.id


def _fetcher(routes: dict[str, httpx.Response], tmp_path: Path) -> tuple[SourceFetcher, list[str]]:
    """routes maps exact URL -> canned response. Anything not listed 404s,
    which conveniently makes robots.txt "not found" (allow-all) the
    default unless a test routes it explicitly. Returns the fetcher and
    the list of URLs actually requested, so tests can assert on what was
    (or wasn't) fetched."""
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        requested.append(url)
        if url in routes:
            return routes[url]
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fetcher = SourceFetcher(client, text_root=tmp_path, min_request_interval_s=0.0)
    return fetcher, requested


async def test_fetch_persists_a_new_source(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    url = "https://www.nytimes.com/1948/11/14/archives/article.html"
    fetcher, requested = _fetcher(
        {url: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})},
        tmp_path,
    )

    source = await fetcher.fetch_source(session, subject_id, url)

    assert source.id is not None
    assert source.subject_id == subject_id
    assert source.domain == "nytimes.com"
    assert source.tier == SourceTier.UNVERIFIED  # never auto Tier A
    assert source.word_count > 25
    assert source.title == "Six Vanish From Bavarian Farmstead"
    assert Path(source.text_path).exists()
    assert "Andreas Gruber" in Path(source.text_path).read_text(encoding="utf-8")
    assert url in requested


async def test_fetch_wikipedia_auto_tags_reference(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    url = "https://en.wikipedia.org/wiki/Hinterkaifeck_murders"
    fetcher, _ = _fetcher(
        {url: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})},
        tmp_path,
    )

    source = await fetcher.fetch_source(session, subject_id, url)

    assert source.tier == SourceTier.REFERENCE


async def test_fetch_caller_can_explicitly_set_tier_a(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """Only the *automatic* path is restricted from Tier A -- a human
    explicitly classifying a source after review is unrestricted."""
    subject_id = _persist_subject(session, strategy_id)
    url = "https://www.courts.gov/case/12345"
    fetcher, _ = _fetcher(
        {url: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})},
        tmp_path,
    )

    source = await fetcher.fetch_source(session, subject_id, url, tier=SourceTier.PRIMARY_RECORD)

    assert source.tier == SourceTier.PRIMARY_RECORD


async def test_fetch_tier_c_domain_rejected_before_any_request(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    fetcher, requested = _fetcher({}, tmp_path)

    with pytest.raises(TierCBlockedDomainError):
        await fetcher.fetch_source(session, subject_id, "https://medium.com/@x/a-retelling")

    assert requested == []  # not even a robots.txt request


async def test_refetching_the_same_url_returns_existing_without_a_new_request(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    url = "https://www.nytimes.com/1948/11/14/archives/article.html"
    fetcher, requested = _fetcher(
        {url: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})},
        tmp_path,
    )

    first = await fetcher.fetch_source(session, subject_id, url)
    request_count_after_first = len(requested)
    second = await fetcher.fetch_source(session, subject_id, url)

    assert second.id == first.id
    assert len(requested) == request_count_after_first  # no new HTTP request at all


async def test_duplicate_content_under_a_different_url_raises(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """A syndicated copy at a second URL must not become a second Source
    row -- see Source's docstring in packages/db/models.py: this would
    silently inflate R1's gate, which has monetization meaning."""
    subject_id = _persist_subject(session, strategy_id)
    url_a = "https://www.papera.com/story"
    url_b = "https://www.paperb.com/syndicated-copy"
    fetcher, _ = _fetcher(
        {
            url_a: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"}),
            url_b: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"}),
        },
        tmp_path,
    )

    original = await fetcher.fetch_source(session, subject_id, url_a)

    with pytest.raises(DuplicateSourceContentError) as exc_info:
        await fetcher.fetch_source(session, subject_id, url_b)

    assert exc_info.value.existing_source_id == original.id


async def test_empty_extraction_is_never_persisted_and_cannot_collide(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """The ordering this whole design depends on: two failed extractions
    must not both hash to sha256("") and collide against Source's
    UniqueConstraint(subject_id, text_sha256) for the wrong reason."""
    subject_id = _persist_subject(session, strategy_id)
    url_a = "https://scans.example.gov/case-a.html"
    url_b = "https://scans.example.gov/case-b.html"
    fetcher, _ = _fetcher(
        {
            url_a: httpx.Response(200, text=THIN_HTML, headers={"content-type": "text/html"}),
            url_b: httpx.Response(200, text=THIN_HTML, headers={"content-type": "text/html"}),
        },
        tmp_path,
    )

    with pytest.raises(EmptyExtractionError):
        await fetcher.fetch_source(session, subject_id, url_a)
    with pytest.raises(EmptyExtractionError):
        await fetcher.fetch_source(session, subject_id, url_b)

    remaining = session.exec(select(Source).where(Source.subject_id == subject_id)).all()
    assert remaining == []


async def test_robots_disallow_blocks_the_fetch(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    url = "https://www.example.com/private/document"
    robots_url = "https://www.example.com/robots.txt"
    fetcher, requested = _fetcher(
        {
            robots_url: httpx.Response(200, text="User-agent: *\nDisallow: /private/\n"),
            url: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"}),
        },
        tmp_path,
    )

    with pytest.raises(RobotsDisallowedError):
        await fetcher.fetch_source(session, subject_id, url)

    assert url not in requested  # robots was checked, the page itself never was


# --------------------------------------------------------------------------
# Domain-reference-sample check (packages/research/boilerplate.py) -- the
# only thing that touches the "200 response, generic error page" failure
# mode. favor_precision + the raised word-count floor handle nav-shaped
# fallback text upstream in extraction; neither can see a well-formed,
# generic page like GENERIC_ERROR_PAGE above, since structurally it's
# indistinguishable from a real short article.
# --------------------------------------------------------------------------


async def test_content_matching_the_domain_root_raises_likely_boilerplate(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    root_url = "https://status.example.com/"
    target_url = "https://status.example.com/incidents/4471"
    fetcher, _ = _fetcher(
        {
            root_url: httpx.Response(
                200, text=GENERIC_ERROR_PAGE, headers={"content-type": "text/html"}
            ),
            target_url: httpx.Response(
                200, text=GENERIC_ERROR_PAGE, headers={"content-type": "text/html"}
            ),
        },
        tmp_path,
    )

    with pytest.raises(LikelyBoilerplateError):
        await fetcher.fetch_source(session, subject_id, target_url)


async def test_content_matching_another_subjects_source_on_the_same_domain_raises(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """Unscoped by subject on purpose: the same template chrome recurring
    across two different subjects researching different cases on the same
    domain is exactly the case the per-subject dedup check cannot see."""
    subject_a = _persist_subject(session, strategy_id, slug="subject-a")
    subject_b = _persist_subject(session, strategy_id, slug="subject-b")
    url_a = "https://status.example.com/incidents/1"
    url_b = "https://status.example.com/incidents/2"
    fetcher, _ = _fetcher(
        {
            url_a: httpx.Response(
                200, text=GENERIC_ERROR_PAGE, headers={"content-type": "text/html"}
            ),
            url_b: httpx.Response(
                200, text=GENERIC_ERROR_PAGE, headers={"content-type": "text/html"}
            ),
        },
        tmp_path,
    )

    await fetcher.fetch_source(session, subject_a, url_a)

    with pytest.raises(LikelyBoilerplateError):
        await fetcher.fetch_source(session, subject_b, url_b)


async def test_domain_root_is_fetched_once_and_cached(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    root_url = "https://www.nytimes.com/"
    url_one = "https://www.nytimes.com/1948/11/14/archives/1.html"
    url_two = "https://www.nytimes.com/1948/11/15/archives/2.html"
    fetcher, requested = _fetcher(
        {
            root_url: httpx.Response(
                200, text=GENERIC_ERROR_PAGE, headers={"content-type": "text/html"}
            ),
            url_one: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"}),
            url_two: httpx.Response(
                200, text=ARTICLE_HTML_TWO, headers={"content-type": "text/html"}
            ),
        },
        tmp_path,
    )

    await fetcher.fetch_source(session, subject_id, url_one)
    await fetcher.fetch_source(session, subject_id, url_two)

    assert requested.count(root_url) == 1


async def test_unreachable_domain_root_does_not_block_the_real_fetch(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    """The reference-sample check exists to improve confidence; it must
    never block the fetch it's checking. A domain root that 404s (no
    special routing below -- the mock transport's default) degrades to
    "no reference for this host," not a failure."""
    subject_id = _persist_subject(session, strategy_id)
    url = "https://www.nytimes.com/1948/11/14/archives/article.html"
    fetcher, _ = _fetcher(
        {url: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})},
        tmp_path,
    )

    source = await fetcher.fetch_source(session, subject_id, url)  # must not raise

    assert source.id is not None


async def test_real_content_differing_from_the_domain_root_is_not_flagged(
    session: Session, strategy_id: int, tmp_path: Path
) -> None:
    subject_id = _persist_subject(session, strategy_id)
    root_url = "https://www.nytimes.com/"
    url = "https://www.nytimes.com/1948/11/14/archives/article.html"
    fetcher, _ = _fetcher(
        {
            root_url: httpx.Response(
                200, text=GENERIC_ERROR_PAGE, headers={"content-type": "text/html"}
            ),
            url: httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"}),
        },
        tmp_path,
    )

    source = await fetcher.fetch_source(session, subject_id, url)  # must not raise

    assert source.word_count > 0
