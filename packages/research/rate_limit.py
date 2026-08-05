"""Generic per-domain rate limiting for source fetching.

docs/ARCHIVE-SPEC.md's per-provider limiting works because there are exactly
five known, enumerated providers with hand-written adapters. Source fetching
hits arbitrary operator-supplied URLs across unbounded domains, so it can't
be a fixed table of per-target rules -- this is a generic minimum-interval
throttle keyed on the same derive_domain() used for tiering and R1's
distinct-domain counting, not the literal host, since "don't hammer this
domain" is about being a good citizen toward the owning organization, not
one specific subdomain's server.
"""

from __future__ import annotations

import asyncio
import time

from packages.domain.urls import derive_domain

DEFAULT_MIN_INTERVAL_S = 2.0


class DomainRateLimiter:
    def __init__(self, min_interval_s: float = DEFAULT_MIN_INTERVAL_S) -> None:
        self._min_interval_s = min_interval_s
        self._last_request_at: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, url: str) -> None:
        domain = derive_domain(url)
        lock = self._locks.setdefault(domain, asyncio.Lock())
        async with lock:
            last = self._last_request_at.get(domain)
            now = time.monotonic()
            if last is not None:
                elapsed = now - last
                remaining = self._min_interval_s - elapsed
                if remaining > 0:
                    await asyncio.sleep(remaining)
            self._last_request_at[domain] = time.monotonic()
