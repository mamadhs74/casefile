"""Per-domain reference-sample cache for detecting templated site chrome
that survives extraction as if it were real content -- see docs/SCHEMA.md's
"Extraction specificity" section for the failure mode this exists to catch,
the alternatives investigated and rejected, and this approach's known
limit.
"""

from __future__ import annotations


class DomainSampleCache:
    """One reference extraction hash per host, fetched once (the domain
    root) and reused for every subsequent fetch from that host -- the same
    caching shape as packages/research/robots.py's RobotsCache. Stores a
    hash, not the raw text, for the same reason Source.text_sha256 is a
    hash: cheap to compare, nothing to hold in memory across a long
    research session's worth of domains.

    None means "no usable reference for this host" (the root fetch or its
    own extraction failed) -- not "not yet checked." A host present in the
    cache has already been resolved one way or the other; a failed
    reference fetch must not be retried on every subsequent fetch from
    that host, and must never block the fetch it was trying to help
    validate.
    """

    def __init__(self) -> None:
        self._sample_hashes: dict[str, str | None] = {}

    def has(self, host: str) -> bool:
        return host in self._sample_hashes

    def get(self, host: str) -> str | None:
        return self._sample_hashes.get(host)

    def set(self, host: str, text_sha256: str | None) -> None:
        self._sample_hashes[host] = text_sha256


class LikelyBoilerplateError(Exception):
    """Extracted text matches this domain's own reference sample (the
    domain root) or another already-fetched Source from the same domain --
    strong evidence of templated site chrome rather than a real duplicate.
    Deliberately a different error from DuplicateSourceContentError: that
    one means "you already have this exact source," this one means "this
    text isn't specific to this page at all."

    Mitigates, but does not solve, a 200 response whose body is a generic
    error or placeholder page: this only catches it when the error page
    happens to match the cached domain-root sample or a previously-fetched
    Source from the same domain, which won't always hold -- an error page
    that differs from both slips through. See docs/SCHEMA.md.
    """

    def __init__(self, url: str, domain: str) -> None:
        self.url = url
        self.domain = domain
        super().__init__(
            f"{url!r} extracted to the same text as {domain!r}'s reference "
            "sample or another source from that domain -- likely site "
            "chrome, not content specific to this page"
        )
