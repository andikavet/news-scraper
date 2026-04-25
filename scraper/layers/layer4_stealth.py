"""Layer 4 — stealth Playwright fetch (anti-anti-bot).

Last rung of the 4-layer cascade. Used when Layers 1-3 have all been
soft-blocked (HTTP 4xx, or HTTP 2xx with a Cloudflare/captcha page that
trips :mod:`scraper.block_detection`). Layer 4 launches Chromium with a
set of patches that defeat the most common fingerprint-based bot checks:

- ``navigator.webdriver`` is set to ``undefined`` (default Playwright
  value leaks ``true``).
- ``navigator.plugins.length`` is made non-zero so plugin-count checks
  pass.
- ``navigator.languages`` is populated with an Indonesian-first locale
  chain to match a typical user on an ID portal.
- ``window.chrome`` is stubbed with a minimal ``runtime`` object.
- ``WebGLRenderingContext.getParameter`` returns realistic Intel/AMD
  vendor strings instead of the Chromium headless default
  (``Google SwiftShader``).
- Default User-Agent is randomized from a small pool of current desktop
  Chrome builds on Windows and macOS, matching the ``Accept-Language``
  chain and platform hint.

The patches are applied via ``context.add_init_script`` so they run
before any page script — the target site sees the patched values even if
it probes the DOM immediately on load.

Speed knobs mirror Layer 3: images / fonts / media are route-blocked so
the browser only loads HTML + CSS + JS. Each fetch uses a fresh browser
process for isolation (a challenge-solving long-lived context would be
more realistic but also more fragile and harder to test).

Layer 4 declares ``parser_name = "bs4"`` — once the stealth context has
convinced the origin to serve real content, the HTML shape is the same
as Layer 1 / Layer 3.
"""

from __future__ import annotations

import logging
import random

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from scraper.layers.base import FetchResult, ScrapeError

logger = logging.getLogger(__name__)

_BLOCKED_RESOURCES = {"image", "media", "font"}

# Small pool of realistic desktop UAs. Kept small deliberately so test
# assertions can reliably cover the rotation without being brittle.
_UA_POOL: tuple[str, ...] = (
    # Windows 10 Chrome 123
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # macOS Chrome 123
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Windows 11 Edge 123 (Chromium-based)
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
)

# JS patches applied before any page script runs. Keep additions here
# strictly scoped to fingerprint-defeating shims — no page-specific logic.
_STEALTH_INIT_SCRIPT = """
// 1. navigator.webdriver -> undefined
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// 2. navigator.plugins -> non-empty array
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer'},
        {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai'},
        {name: 'Native Client', filename: 'internal-nacl-plugin'},
    ],
});

// 3. navigator.languages -> ID-first locale chain
Object.defineProperty(navigator, 'languages', {get: () => ['id-ID', 'id', 'en-US', 'en']});

// 4. window.chrome stub (headless Chromium omits this by default)
window.chrome = window.chrome || {runtime: {}};

// 5. Spoof the WebGL vendor strings (headless uses SwiftShader → obvious tell)
const getParameter = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function(parameter) {
    // UNMASKED_VENDOR_WEBGL
    if (parameter === 37445) return 'Intel Inc.';
    // UNMASKED_RENDERER_WEBGL
    if (parameter === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.apply(this, [parameter]);
};
"""


class Layer4Stealth:
    """Playwright + stealth init-script fingerprint patches."""

    layer_number = 4
    name = "playwright-stealth"
    parser_name = "bs4"

    def __init__(
        self,
        ua_pool: tuple[str, ...] | None = None,
        block_resources: bool = True,
        wait_until: str = "networkidle",
        rng: random.Random | None = None,
    ) -> None:
        self._ua_pool: tuple[str, ...] = tuple(ua_pool) if ua_pool is not None else _UA_POOL
        if not self._ua_pool:
            raise ValueError("Layer4Stealth requires at least one UA in ua_pool")
        self._block_resources = block_resources
        self._wait_until = wait_until
        self._rng = rng if rng is not None else random.Random()

    def _pick_user_agent(self) -> str:
        """Random UA from pool. Deterministic when a seeded ``rng`` is injected."""
        return self._rng.choice(self._ua_pool)

    def fetch(self, url: str, timeout: float = 30.0) -> FetchResult:
        """Render ``url`` with stealth-patched Chromium, return the HTML."""
        ua = self._pick_user_agent()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                    ],
                )
                try:
                    context = browser.new_context(
                        user_agent=ua,
                        locale="id-ID",
                        timezone_id="Asia/Jakarta",
                        viewport={"width": 1366, "height": 768},
                        extra_http_headers={
                            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                        },
                    )
                    context.add_init_script(_STEALTH_INIT_SCRIPT)
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
                        raise ScrapeError(f"layer4 navigation timeout: {e}") from e
                    status = response.status if response is not None else None
                    if status is not None and status >= 400:
                        raise ScrapeError(f"layer4 HTTP {status} for {url}")
                    html = page.content()
                    final_url = page.url
                    context.close()
                    return FetchResult(url=final_url, html=html, status_code=status)
                finally:
                    browser.close()
        except ScrapeError:
            raise
        except PlaywrightError as e:
            raise ScrapeError(f"layer4 playwright error: {e}") from e


def _block_heavy_resources(route, request) -> None:  # type: ignore[no-untyped-def]
    if request.resource_type in _BLOCKED_RESOURCES:
        route.abort()
    else:
        route.continue_()


__all__ = ["Layer4Stealth"]
