"""film-tv-news' own tier-assignment rule.

packages/research/tiering.py's default (REFERENCE_DOMAINS or UNVERIFIED,
never Tier A) exists because determining whether a source is
contemporaneous requires comparing an event date to a publication date --
real human judgment a domain alone cannot make for a case that may be
decades old. That judgment doesn't exist for this strategy: a
film-tv-news Subject is one week of coverage, and every article this
strategy fetches is published within days of the event it reports --
docs/SOURCING.md's own Tier A definition already names "contemporaneous
newspaper reporting" explicitly. Contemporaneity here is structural, not
a case-by-case call, so this strategy registers its own assigner rather
than using packages/research/tiering.py's default -- see that module's
own docstring for the registration mechanism.

CONTEMPORANEOUS_DOMAINS is deliberately narrow: the five domains checked
for reachability when this strategy was built (see docs/HANDOFF.md
finding #35), not a general "trusted news domain" list. Anything else
still lands UNVERIFIED, same as before this module existed.
"""

from __future__ import annotations

from packages.domain.enums import SourceTier
from packages.domain.urls import derive_domain
from packages.research.tiering import register_tier_assigner

STRATEGY_SLUG = "film-tv-news"  # must match packages.strategies.film_tv_news.SLUG;
# not imported from there to avoid this submodule depending on its own
# parent package's __init__ module -- tests/test_tiering.py checks the two
# stay in sync.

CONTEMPORANEOUS_DOMAINS: frozenset[str] = frozenset(
    {
        "variety.com",
        "hollywoodreporter.com",
        "deadline.com",
        "thewrap.com",
        "indiewire.com",
    }
)


def assign_tier(url: str) -> SourceTier:
    domain = derive_domain(url)
    if domain in CONTEMPORANEOUS_DOMAINS:
        return SourceTier.CONTEMPORANEOUS
    return SourceTier.UNVERIFIED


register_tier_assigner(STRATEGY_SLUG, assign_tier)
