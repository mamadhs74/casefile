"""Shared URL utilities.

Domain derivation lives here, not duplicated between packages/db/listeners.py
(Source.domain) and packages/research/ (Tier C blocklist checks, dedup by
domain). Both need exactly the same notion of "domain" -- www./amp./bare all
collapsing to one registrable domain -- and drift between two independent
implementations would be a real bug, not a style nit: R1's gate counts
distinct domains for independence, so a slightly different derivation in one
place could silently change what counts as independent sourcing.
"""

from __future__ import annotations

import tldextract

# suffix_list_urls=() disables tldextract's live fetch of the Public Suffix
# List, so domain derivation never makes a network call and is deterministic
# in tests and CI -- it uses the snapshot bundled with the package.
_extract = tldextract.TLDExtract(suffix_list_urls=())


def derive_domain(url: str) -> str:
    extracted = _extract(url)
    if extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}".lower()
    return extracted.domain.lower()
