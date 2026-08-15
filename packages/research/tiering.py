"""Tier C exclusion and initial tier assignment -- docs/SOURCING.md's source
tiers, enforcement not convention.

"Domain heuristics may never write Tier A" is criminal-cases' rule, not a
global invariant -- it is the *default* behavior here (nothing registered
for a strategy_slug), because determining contemporaneity for a criminal
case requires comparing an event date to a publication date, which is real
human judgment a domain alone cannot make. A .gov domain can just as easily
host a blog post about a case as the court filing itself. For a strategy
where that judgment is structural rather than case-by-case (see
packages/strategies/film_tv_news/tiering.py's own docstring), that
strategy owns the exception, the same way it owns its eligibility scorer
-- this module does not special-case any one strategy by name.

A strategy that wants to auto-assign Tier A registers its own assigner via
register_tier_assigner, as an import side effect -- the same pattern
packages.research.dispatch.register_strategy uses for eligibility. This
module never imports a strategy package directly: packages/strategies/*
already depends on packages/research/* (never the reverse), and importing
a strategy from here would invert that, plus pay the cost of every
registered strategy's own import side effects just to import this module.
"""

from __future__ import annotations

from collections.abc import Callable

from packages.domain.enums import SourceTier
from packages.domain.urls import derive_domain

# Never read, never ingested, never used -- docs/SOURCING.md's Tier C.
# Starts sparse and is expected to grow from real rejections, the same way
# docs/ARCHIVE-SPEC.md describes growing its license-fixtures file. Domain-
# level blocking to start, not path-level. Code-reviewed, not runtime-
# editable -- same reasoning Strategy's own gate thresholds get in
# docs/SCHEMA.md: weakening this requires a change someone reviews.
TIER_C_BLOCKED_DOMAINS: frozenset[str] = frozenset(
    {
        # Content-farm article aggregators.
        "medium.com",
        # Podcast transcript / show-notes hosts.
        "podcasts.apple.com",
    }
)

# Wikipedia and reference wikis -- docs/SOURCING.md's Tier B, "may be used
# to find Tier A sources, may never be a source ID on a claim." Detection
# here is essentially unambiguous, and the ceiling is Tier B regardless of
# whether a given article turns out to be a great lead or a bad one, so a
# wrong guess costs nothing -- unlike Tier A, this one is safe to automate.
# criminal-cases' own domain list: unchanged, unmoved, and used by every
# strategy that does not register its own assigner below.
REFERENCE_DOMAINS: frozenset[str] = frozenset(
    {
        "wikipedia.org",
        "wikimedia.org",
        "britannica.com",
    }
)

# Populated by each strategy that needs one, as an import side effect --
# see module docstring. Absent here entirely means "use this module's own
# REFERENCE_DOMAINS/UNVERIFIED default," not "error."
_TIER_ASSIGNERS: dict[str, Callable[[str], SourceTier]] = {}


class TierCBlockedDomainError(Exception):
    """The URL's domain is on the Tier C blocklist -- never read, never
    ingested, never used. Raised before any network request is made,
    including a robots.txt fetch."""

    def __init__(self, url: str, domain: str) -> None:
        self.url = url
        self.domain = domain
        super().__init__(f"{url!r} is on the Tier C blocklist (domain {domain!r})")


def check_not_tier_c(url: str) -> None:
    domain = derive_domain(url)
    if domain in TIER_C_BLOCKED_DOMAINS:
        raise TierCBlockedDomainError(url, domain)


def register_tier_assigner(strategy_slug: str, assigner: Callable[[str], SourceTier]) -> None:
    """A strategy registers its own assign_initial_tier override here. See
    module docstring for why this is a registration hook rather than an
    import inside this module."""
    _TIER_ASSIGNERS[strategy_slug] = assigner


def assign_initial_tier(url: str, strategy_slug: str) -> SourceTier:
    """Called only after check_not_tier_c() has already passed.

    Never returns a Tier A value for a strategy that hasn't registered its
    own assigner -- see module docstring. A strategy that has (currently:
    only film-tv-news) may return a Tier A value; that restriction is now
    owned per-strategy, not enforced globally by this function.
    """
    assigner = _TIER_ASSIGNERS.get(strategy_slug)
    if assigner is not None:
        return assigner(url)

    domain = derive_domain(url)
    if domain in REFERENCE_DOMAINS:
        return SourceTier.REFERENCE
    return SourceTier.UNVERIFIED
