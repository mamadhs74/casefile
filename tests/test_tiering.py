"""docs/SOURCING.md's tier assignment: heuristics may only ever write Tier
B or UNVERIFIED, never Tier A -- see packages/research/tiering.py's module
docstring for the asymmetric-risk reasoning."""

from __future__ import annotations

import pytest

from packages.domain.enums import SourceTier
from packages.research.tiering import (
    TierCBlockedDomainError,
    assign_initial_tier,
    check_not_tier_c,
)


def test_blocked_domain_raises() -> None:
    with pytest.raises(TierCBlockedDomainError):
        check_not_tier_c("https://medium.com/@someone/a-true-crime-retelling")


def test_non_blocked_domain_does_not_raise() -> None:
    check_not_tier_c("https://www.nytimes.com/1948/11/14/archives/article.html")  # must not raise


def test_wikipedia_auto_assigns_reference() -> None:
    assert assign_initial_tier("https://en.wikipedia.org/wiki/Some_Case") == SourceTier.REFERENCE


def test_unrecognized_domain_defaults_unverified() -> None:
    assert assign_initial_tier("https://www.nytimes.com/1948/11/14/archives/1.html") == (
        SourceTier.UNVERIFIED
    )


def test_gov_domain_defaults_unverified_not_primary_record() -> None:
    """The asymmetric-risk case this design is built around: a .gov domain
    can host a blog post about a case as easily as the court filing
    itself, so domain alone never writes a Tier A value, even here."""
    assert assign_initial_tier("https://www.courts.gov/case/12345") == SourceTier.UNVERIFIED


def test_book_domains_are_left_unautomated() -> None:
    """No book-domain heuristic exists -- archive.org book items default to
    UNVERIFIED same as anything else unrecognized, per the agreed scope."""
    assert assign_initial_tier("https://archive.org/details/somebook1948") == (
        SourceTier.UNVERIFIED
    )
