"""Layer 1 — static HTML fetch via ``httpx`` (fastest path).

Used for portals whose listing pages render server-side. If the selectors
find nothing or the response is blocked / redirected, the runner escalates to
the next enabled layer.
"""

from __future__ import annotations

import httpx

from scraper.layers.base import FetchResult, ScrapeError

_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


class Layer1Httpx:
    """Plain synchronous HTTP GET with browser-like headers."""

    layer_number = 1
    name = "httpx+bs4"

    def __init__(self, user_agent: str = _DEFAULT_UA) -> None:
        self._user_agent = user_agent

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        headers = {
            "User-Agent": self._user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "id,en-US;q=0.9,en;q=0.8",
        }
        try:
            with httpx.Client(
                follow_redirects=True,
                http2=True,
                timeout=timeout,
                headers=headers,
            ) as client:
                resp = client.get(url)
        except httpx.HTTPError as e:
            raise ScrapeError(f"layer1 network error: {e}") from e

        if resp.status_code >= 400:
            raise ScrapeError(
                f"layer1 HTTP {resp.status_code} for {url}",
            )
        return FetchResult(url=str(resp.url), html=resp.text, status_code=resp.status_code)


__all__ = ["Layer1Httpx"]
