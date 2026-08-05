"""packages/research/robots.py against a mocked transport -- no real
network, matching docs/ARCHIVE-SPEC.md's testing guidance for the sibling
retrieval package."""

from __future__ import annotations

import httpx
import pytest

from packages.research.robots import RobotsCache, RobotsDisallowedError, RobotsUnreachableError


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


async def test_missing_robots_txt_allows_fetch() -> None:
    """RFC 9309: no robots.txt at all means allow-all, not deny-all."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    async with _client(httpx.MockTransport(handler)) as client:
        cache = RobotsCache(client, "casefile-test-bot/1.0")
        await cache.check("https://example.com/some/page")  # must not raise


async def test_disallowed_path_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")

    async with _client(httpx.MockTransport(handler)) as client:
        cache = RobotsCache(client, "casefile-test-bot/1.0")
        with pytest.raises(RobotsDisallowedError):
            await cache.check("https://example.com/private/document")


async def test_allowed_path_does_not_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")

    async with _client(httpx.MockTransport(handler)) as client:
        cache = RobotsCache(client, "casefile-test-bot/1.0")
        await cache.check("https://example.com/public/document")  # must not raise


async def test_robots_unreachable_on_server_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    async with _client(httpx.MockTransport(handler)) as client:
        cache = RobotsCache(client, "casefile-test-bot/1.0")
        with pytest.raises(RobotsUnreachableError):
            await cache.check("https://example.com/page")


async def test_robots_unreachable_on_connection_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    async with _client(httpx.MockTransport(handler)) as client:
        cache = RobotsCache(client, "casefile-test-bot/1.0")
        with pytest.raises(RobotsUnreachableError):
            await cache.check("https://example.com/page")


async def test_robots_txt_is_fetched_once_and_cached_per_host() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(200, text="User-agent: *\nDisallow:\n")

    async with _client(httpx.MockTransport(handler)) as client:
        cache = RobotsCache(client, "casefile-test-bot/1.0")
        await cache.check("https://example.com/page-one")
        await cache.check("https://example.com/page-two")
        await cache.check("https://example.com/page-three")

    assert request_count == 1
