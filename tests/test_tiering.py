"""docs/SOURCING.md's tier assignment. packages/research/tiering.py's own
default (Tier B/UNVERIFIED, never Tier A) is criminal-cases' rule, proven
unchanged here; film-tv-news registers its own exception -- see that
module's docstring and packages/strategies/film_tv_news/tiering.py's."""

from __future__ import annotations

import pytest

from packages.domain.enums import SourceTier
from packages.research.tiering import (
    TierCBlockedDomainError,
    assign_initial_tier,
    check_not_tier_c,
)
from packages.strategies.criminal_cases import SLUG as CRIMINAL_CASES_SLUG
from packages.strategies.film_tv_news import SLUG as FILM_TV_NEWS_SLUG


def test_blocked_domain_raises() -> None:
    with pytest.raises(TierCBlockedDomainError):
        check_not_tier_c("https://medium.com/@someone/a-true-crime-retelling")


def test_non_blocked_domain_does_not_raise() -> None:
    check_not_tier_c("https://www.nytimes.com/1948/11/14/archives/article.html")  # must not raise


def test_wikipedia_auto_assigns_reference_for_criminal_cases() -> None:
    assert (
        assign_initial_tier("https://en.wikipedia.org/wiki/Some_Case", CRIMINAL_CASES_SLUG)
        == SourceTier.REFERENCE
    )


def test_unrecognized_domain_defaults_unverified_for_criminal_cases() -> None:
    url = "https://www.nytimes.com/1948/11/14/archives/1.html"
    assert assign_initial_tier(url, CRIMINAL_CASES_SLUG) == SourceTier.UNVERIFIED


def test_gov_domain_defaults_unverified_not_primary_record_for_criminal_cases() -> None:
    """The asymmetric-risk case this design is built around: a .gov domain
    can host a blog post about a case as easily as the court filing
    itself, so domain alone never writes a Tier A value for criminal-cases,
    even here."""
    assert (
        assign_initial_tier("https://www.courts.gov/case/12345", CRIMINAL_CASES_SLUG)
        == SourceTier.UNVERIFIED
    )


def test_book_domains_are_left_unautomated_for_criminal_cases() -> None:
    """No book-domain heuristic exists -- archive.org book items default to
    UNVERIFIED same as anything else unrecognized, per the agreed scope."""
    assert (
        assign_initial_tier("https://archive.org/details/somebook1948", CRIMINAL_CASES_SLUG)
        == SourceTier.UNVERIFIED
    )


def test_unregistered_strategy_gets_the_same_default_as_criminal_cases() -> None:
    """The default isn't special-cased to criminal-cases' own slug -- any
    strategy that hasn't registered an assigner gets it, so a hypothetical
    third strategy is covered by construction, not by remembering to add
    it here."""
    assert (
        assign_initial_tier("https://en.wikipedia.org/wiki/Some_Case", "some-future-strategy")
        == SourceTier.REFERENCE
    )
    assert (
        assign_initial_tier("https://www.courts.gov/case/12345", "some-future-strategy")
        == SourceTier.UNVERIFIED
    )


def test_film_tv_news_trade_domain_gets_contemporaneous() -> None:
    url = "https://variety.com/2026/film/news/example-1234567/"
    assert assign_initial_tier(url, FILM_TV_NEWS_SLUG) == SourceTier.CONTEMPORANEOUS


def test_film_tv_news_unknown_domain_still_gets_unverified() -> None:
    url = "https://www.nytimes.com/2026/08/15/movies/example.html"
    assert assign_initial_tier(url, FILM_TV_NEWS_SLUG) == SourceTier.UNVERIFIED


def test_film_tv_news_does_not_fall_through_to_reference_domains() -> None:
    """film-tv-news registered its own assigner entirely -- it does not
    fall through to criminal-cases' REFERENCE_DOMAINS at all, wikipedia.org
    included."""
    url = "https://en.wikipedia.org/wiki/Variety_(magazine)"
    assert assign_initial_tier(url, FILM_TV_NEWS_SLUG) == SourceTier.UNVERIFIED


def test_film_tv_news_slug_constant_matches_its_tiering_module() -> None:
    """packages/strategies/film_tv_news/tiering.py hardcodes its own slug
    string rather than importing SLUG from its own package's __init__ (see
    that module's own comment on why) -- this is the check that catches
    the two drifting apart."""
    from packages.strategies.film_tv_news.tiering import STRATEGY_SLUG

    assert STRATEGY_SLUG == FILM_TV_NEWS_SLUG
