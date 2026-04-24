"""Layer 2 — httpx fetch with a mobile-Chrome fingerprint + selectolax parser.

Positioned between Layer 1 (desktop-Chrome httpx + BS4) and Layer 3
(headless Chromium) in the fallback cascade. Two escalations vs Layer 1:

1. **Different HTTP fingerprint** — mobile Safari-on-iOS ``User-Agent`` and
   ``Accept-Language: id-ID`` headers. Some portals aggressively rate-limit
   or 403 the default desktop-Chrome UA but still serve mobile clients;
   when that happens Layer 1 raises and Layer 2 can get through.
2. **Different parser** — selectolax's lexbor backend is considerably more
   tolerant of malformed HTML than lxml. If a page is mangled enough that
   lxml produces 0 containers, selectolax may still recover the items.

Layer 2 still does not execute JavaScript — if the listing is rendered
client-side, Layer 3 is the right tool.
"""

from __future__ import annotations

import httpx

from scraper.layers.base import FetchResult, ScrapeError

_MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.2 Mobile/15E148 Safari/604.1"
)


class Layer2Selectolax:
    """httpx fetch with a mobile User-Agent; paired with the selectolax parser."""

    layer_number = 2
    name = "httpx-mobile+selectolax"
    parser_name = "selectolax"

    def __init__(self, user_agent: str = _MOBILE_UA) -> None:
        self._user_agent = user_agent

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        headers = {
            "User-Agent": self._user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
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
            raise ScrapeError(f"layer2 network error: {e}") from e

        if resp.status_code >= 400:
            raise ScrapeError(
                f"layer2 HTTP {resp.status_code} for {url}",
            )
        return FetchResult(url=str(resp.url), html=resp.text, status_code=resp.status_code)


__all__ = ["Layer2Selectolax"]
