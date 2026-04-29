"""Layer 3 — JS-rendered page fetch via Playwright (Chromium).

Used when a portal renders its listing client-side (React/Vue/etc.) so
``httpx`` sees an empty shell. Layer 3 boots a headless Chromium, waits
for the listing to be **actually present in the DOM**, and returns the
rendered HTML.

Wait strategy (Iter 14 refactor — the Iter 7 ``networkidle`` default was
unreliable):

- Default navigation gate is ``wait_until="domcontentloaded"``. That
  fires as soon as the HTML has parsed and inline ``<script>`` tags have
  run — everything needed for a JS framework to start hydrating.
- When the caller passes a ``wait_selector`` (always the source's
  container selector, plumbed in by the orchestrator), the layer blocks
  on ``page.wait_for_selector(wait_selector, state="attached")`` after
  navigation. This is the only reliable signal that the listing is
  actually visible — ``networkidle`` never settles on ad-heavy news
  portals because analytics / ad SDKs fire continuous beacons and keep
  the "idle" threshold from being reached.
- When no ``wait_selector`` is provided, the layer falls back to
  ``wait_until="load"`` — strictly weaker than ``networkidle`` but
  reliable. Tests / legacy callers that don't know the selector still
  get a rendered page.

Layer 3 implements the ``fetch(url, timeout, *, wait_selector=None) ->
FetchResult`` interface from :mod:`scraper.layers.base`, so it is a
drop-in for ``url_params`` sources. JS-driven pagination strategies
(``infinite_scroll`` / ``click_next``) cannot use this single-shot
interface because they need to preserve browser state across pages —
those are handled by :mod:`scraper.playwright_session`.

Speed knobs:
- Images, media, and fonts are route-blocked so the browser only loads
  HTML, CSS, and JS. For most Indonesian news portals this cuts page
  weight by 70-90%.
- The browser launches with ``--no-sandbox`` + ``--disable-dev-shm-usage``
  so it works in containerized CI environments and inside Docker.
- A fresh browser per fetch is used for isolation. For many sequential
  fetches, use ``BrowserSession`` which keeps one context alive.
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
_DEFAULT_LAUNCH_ARGS = (
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
)


class Layer3Playwright:
    """Single-shot Playwright fetch compatible with the Layer interface."""

    layer_number = 3
    name = "playwright"
    parser_name = "bs4"

    def __init__(
        self,
        user_agent: str = _DEFAULT_UA,
        block_resources: bool = True,
    ) -> None:
        self._user_agent = user_agent
        self._block_resources = block_resources

    def fetch(
        self,
        url: str,
        timeout: float = 30.0,
        *,
        wait_selector: str | None = None,
    ) -> FetchResult:
        """Render ``url`` with Chromium, return the resulting HTML.

        ``timeout`` is expressed in seconds and applied to navigation +
        any ``wait_for_selector`` together — the layer splits the budget
        so a slow navigation still leaves room to wait for the listing.

        When ``wait_selector`` is truthy, the layer waits for that CSS
        selector to attach to the DOM before reading ``page.content()``.
        When it is ``None``, the layer waits for the ``load`` lifecycle
        event only (no selector-specific wait).
        """
        timeout_ms = int(timeout * 1000)
        # Split the budget roughly 60/40 between navigation and selector
        # wait. Experimentally, `domcontentloaded` on ad-heavy news sites
        # returns in 1-3s, leaving the bulk for JS hydration.
        nav_timeout_ms = max(5_000, int(timeout_ms * 0.6))
        selector_timeout_ms = max(3_000, timeout_ms - nav_timeout_ms)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=list(_DEFAULT_LAUNCH_ARGS),
                )
                try:
                    context = browser.new_context(user_agent=self._user_agent)
                    page = context.new_page()
                    if self._block_resources:
                        page.route("**/*", _block_heavy_resources)
                    try:
                        response = page.goto(
                            url,
                            wait_until="domcontentloaded" if wait_selector else "load",
                            timeout=nav_timeout_ms,
                        )
                    except PlaywrightTimeoutError as e:
                        raise ScrapeError(f"layer3 navigation timeout: {e}") from e
                    status = response.status if response is not None else None
                    if status is not None and status >= 400:
                        raise ScrapeError(f"layer3 HTTP {status} for {url}")
                    if wait_selector:
                        try:
                            page.wait_for_selector(
                                wait_selector,
                                state="attached",
                                timeout=selector_timeout_ms,
                            )
                        except PlaywrightTimeoutError as e:
                            raise ScrapeError(
                                f"layer3 selector '{wait_selector}' did not appear "
                                f"within {selector_timeout_ms}ms: {e}"
                            ) from e
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
