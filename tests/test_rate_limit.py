"""packages/research/rate_limit.py -- generic per-domain throttle."""

from __future__ import annotations

import time

from packages.research.rate_limit import DomainRateLimiter


async def test_second_request_to_same_domain_waits() -> None:
    limiter = DomainRateLimiter(min_interval_s=0.1)

    start = time.monotonic()
    await limiter.wait("https://example.com/1")
    await limiter.wait("https://example.com/2")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.1


async def test_different_domains_do_not_wait_for_each_other() -> None:
    limiter = DomainRateLimiter(min_interval_s=5.0)

    start = time.monotonic()
    await limiter.wait("https://a.com/1")
    await limiter.wait("https://b.com/1")
    elapsed = time.monotonic() - start

    assert elapsed < 1.0


async def test_subdomains_of_the_same_registrable_domain_share_the_throttle() -> None:
    """Rate limiting is keyed on the collapsed registrable domain, same as
    tiering and R1's distinct-domain counting -- www./blog. subdomains of
    one organization share one clock."""
    limiter = DomainRateLimiter(min_interval_s=0.1)

    start = time.monotonic()
    await limiter.wait("https://www.example.com/1")
    await limiter.wait("https://blog.example.com/1")
    elapsed = time.monotonic() - start

    assert elapsed >= 0.1
