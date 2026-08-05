"""Tier C exclusion and initial tier assignment -- docs/SOURCING.md's source
tiers, enforcement not convention.

Domain heuristics may only ever write Tier B or UNVERIFIED, never Tier A.
The risk is asymmetric: a source wrongly left at UNVERIFIED just sits as an
unclassified lead until a researcher looks at it (harmless -- that's Tier
B's actual role even for something that's really Tier A). A source wrongly
*auto*-assigned PRIMARY_RECORD or CONTEMPORANEOUS could let a bad source
into a narratable claim, which is the exact thing packages/db/listeners.py's
five narratable-sourcing listeners exist to prevent. A .gov domain can just
as easily host a blog post about a case as the court filing itself --
domain alone should never write a Tier A value. Promotion to Tier A is a
deliberate human action (a plain field update after review), not something
this module does.
"""

from __future__ import annotations

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
REFERENCE_DOMAINS: frozenset[str] = frozenset(
    {
        "wikipedia.org",
        "wikimedia.org",
        "britannica.com",
    }
)


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


def assign_initial_tier(url: str) -> SourceTier:
    """Called only after check_not_tier_c() has already passed. Never
    returns a Tier A value -- see module docstring."""
    domain = derive_domain(url)
    if domain in REFERENCE_DOMAINS:
        return SourceTier.REFERENCE
    return SourceTier.UNVERIFIED
