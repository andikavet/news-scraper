"""Layer 3 — JS-rendered page fetch via Playwright (Chromium).

Used when a portal renders its listing client-side (React/Vue/etc.) so
``httpx`` sees an empty shell. Layer 3 boots a real headless Chromium, waits
for the network to quiesce, and returns the rendered DOM's HTML.

Layer 3 implements the same ``fetch(url) -> FetchResult`` interface as
Layer 1, so it is a drop-in for ``url_params`` sources. JS-driven pagination
strategies (``infinite_scroll`` / ``click_next``) cannot use this single-shot
interface because they need to preserve browser state across pages — those
are handled by :mod:`scraper.playwright_session` instead.

Speed knobs:
- Images, media, and fonts are route-blocked so the browser only loads HTML,
  CSS, and JS. For most Indonesian news portals this cuts page weight by
  70-90%.
- The browser is launched fresh per fetch for isolation. If you need many
  sequential fetches, use ``BrowserSession`` which keeps one context alive.
"""

from __future__ import annotations

import logging

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from scraper.layers.base import FetchResult, ScrapeError

logger = logging.getLogger(__name__)

_BLOCKED_RESOURCES = {"image", "media", "font"}
_DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


class Layer3Playwright:
    """Single-shot Playwright fetch compatible with the Layer interface."""

    layer_number = 3
    name = "playwright"

    def __init__(
        self,
        user_agent: str = _DEFAULT_UA,
        block_resources: bool = True,
        wait_until: str = "networkidle",
    ) -> None:
        self._user_agent = user_agent
        self._block_resources = block_resources
        self._wait_until = wait_until

    def fetch(self, url: str, timeout: float = 20.0) -> FetchResult:
        """Render ``url`` with Chromium, return the resulting HTML.

        Timeout is expressed in seconds and applied to navigation only; the
        per-route block handler is effectively instant so it doesn't count
        against the budget.
        """
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    context = browser.new_context(user_agent=self._user_agent)
                    page = context.new_page()
                    if self._block_resources:
                        page.route("**/*", _block_heavy_resources)
                    try:
                        response = page.goto(
                            url,
                            wait_until=self._wait_until,
                            timeout=int(timeout * 1000),
                        )
                    except PlaywrightTimeoutError as e:
                        raise ScrapeError(f"layer3 navigation timeout: {e}") from e
                    status = response.status if response is not None else None
                    if status is not None and status >= 400:
                        raise ScrapeError(f"layer3 HTTP {status} for {url}")
                    html = page.content()
                    final_url = page.url
                    context.close()
                    return FetchResult(url=final_url, html=html, status_code=status)
                finally:
                    browser.close()
        except ScrapeError:
            raise
        except PlaywrightError as e:
            raise ScrapeError(f"layer3 playwright error: {e}") from e


def _block_heavy_resources(route, request) -> None:  # type: ignore[no-untyped-def]
    if request.resource_type in _BLOCKED_RESOURCES:
        route.abort()
    else:
        route.continue_()


__all__ = ["Layer3Playwright"]
