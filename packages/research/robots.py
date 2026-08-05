"""robots.txt enforcement, cached per host.

Keyed on the URL's exact host (scheme + netloc), not the collapsed
registrable domain packages/domain/urls.derive_domain() computes for tiering
and rate limiting -- robots.txt is a per-origin document under RFC 9309;
blog.example.com and example.com can legitimately serve different ones even
though they're "the same domain" for our diversity-counting purposes.

Fetched once per host and cached for the life of a SourceFetcher, not
per-URL -- an operator fetching a dozen URLs from one site should cost one
robots.txt request, not a dozen.
"""

from __future__ import annotations

import urllib.robotparser
from urllib.parse import urlsplit

import httpx

ROBOTS_FETCH_TIMEOUT_S = 10.0


class RobotsDisallowedError(Exception):
    """robots.txt explicitly disallows fetching this URL for our user agent."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"robots.txt disallows fetching {url!r}")


class RobotsUnreachableError(Exception):
    """robots.txt could not be fetched for a reason other than "doesn't
    exist" (which is allow-all, per RFC 9309) -- timeout, connection error,
    or a non-404 error status. Treated conservatively: skip the fetch
    rather than assume permission. Retryable -- the site may just be
    temporarily down."""

    def __init__(self, host: str, reason: str) -> None:
        self.host = host
        self.reason = reason
        super().__init__(f"could not fetch robots.txt for {host!r}: {reason}")


class RobotsCache:
    def __init__(self, client: httpx.AsyncClient, user_agent: str) -> None:
        self._client = client
        self._user_agent = user_agent
        # None means "no robots.txt for this host" -- allow all.
        self._parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    async def check(self, url: str) -> None:
        """Raises RobotsDisallowedError or RobotsUnreachableError. Returns
        normally if the fetch is allowed."""
        parts = urlsplit(url)
        host = parts.netloc.lower()

        if host not in self._parsers:
            self._parsers[host] = await self._fetch_and_parse(parts.scheme, host)

        parser = self._parsers[host]
        if parser is not None and not parser.can_fetch(self._user_agent, url):
            raise RobotsDisallowedError(url)

    async def _fetch_and_parse(
        self, scheme: str, host: str
    ) -> urllib.robotparser.RobotFileParser | None:
        robots_url = f"{scheme}://{host}/robots.txt"
        try:
            response = await self._client.get(robots_url, timeout=ROBOTS_FETCH_TIMEOUT_S)
        except httpx.HTTPError as exc:
            raise RobotsUnreachableError(host, str(exc)) from exc

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise RobotsUnreachableError(host, f"HTTP {response.status_code}")

        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser
